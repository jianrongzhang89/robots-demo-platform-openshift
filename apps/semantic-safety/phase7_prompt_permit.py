"""Short-lived signed permits for Phase 7 prompt transitions.

The issuer belongs in the trusted motion/operator control process. This module
contains no ROS dependency so that process and the perception adapter can share
the permit format. A permit is only an assertion by the trusted issuer; the
adapter verifies its signature, scope, freshness and single-use nonce.
"""
from collections import deque
import hashlib
import hmac
import json
import math
import secrets
import threading
import time

PERMIT_SCHEMA = "semantic-prompt-transition-permit/v1"
PERMIT_TTL_NS = 5_000_000_000
MIN_STATIONARY_NS = 250_000_000
MAX_STATUS_AGE_NS = 100_000_000


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _valid_motion_proof(proof, issued_wall_ns):
    if not isinstance(proof, dict):
        return False
    epoch = proof.get("native_epoch")
    seq, wall = proof.get("sample_sequence"), proof.get("sample_wall_ns")
    quiet_since = proof.get("quiet_since_wall_ns")
    if not isinstance(epoch, str) or not 1 <= len(epoch) <= 128:
        return False
    if type(seq) is not int or seq < 1 or type(wall) is not int or type(quiet_since) is not int:
        return False
    if not 0 <= issued_wall_ns - wall < MAX_STATUS_AGE_NS:
        return False
    if not 0 <= issued_wall_ns - quiet_since or issued_wall_ns - quiet_since < MIN_STATIONARY_NS:
        return False
    for name, limit in (("speed", .005), ("angular_speed", .02)):
        value = proof.get(name)
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0 or value >= limit:
            return False
    return (proof.get("applied_vx") == 0 and proof.get("applied_wz") == 0
            and proof.get("armed") is False and proof.get("pending") is False
            and proof.get("paused") is False)


def issue_prompt_permit(*, prompt, generation, stream_epoch, approved_prompts, operator_credential,
                        expected_operator_credential, operator_id, clock, key,
                        now_wall_ns=None, nonce=None):
    """Sign a prompt-scoped permit only after native quiet and operator auth."""
    now = time.time_ns() if now_wall_ns is None else now_wall_ns
    key = bytes(key)
    if len(key) < 32:
        raise ValueError("permit signing key must contain at least 32 bytes")
    if not hmac.compare_digest(str(operator_credential), str(expected_operator_credential)):
        raise PermissionError("operator authorization failed")
    if not isinstance(prompt, str) or prompt not in tuple(approved_prompts):
        raise ValueError("prompt is not in the approved identity")
    if type(generation) is not int or generation < 2:
        raise ValueError("transition generation must be at least 2")
    if not isinstance(stream_epoch, str) or not 1 <= len(stream_epoch) <= 128:
        raise ValueError("bounded adapter stream epoch required")
    if not isinstance(operator_id, str) or not 1 <= len(operator_id) <= 128:
        raise ValueError("bounded operator identity required")
    if not clock.stationary(now):
        raise PermissionError("native motion evidence does not prove stationarity")
    status = clock.status or {}
    physical = status.get("physical") or {}
    proof = {
        "native_epoch": clock.epoch,
        "sample_sequence": physical.get("sequence"),
        "sample_wall_ns": physical.get("wall_ns"),
        "quiet_since_wall_ns": clock.quiet_since,
        "speed": physical.get("speed"),
        "angular_speed": physical.get("angular_speed"),
        "applied_vx": status.get("applied_vx"),
        "applied_wz": status.get("applied_wz"),
        "armed": status.get("armed"),
        "pending": status.get("pending"),
        "paused": physical.get("paused"),
    }
    if not _valid_motion_proof(proof, now):
        raise PermissionError("native motion proof is stale, moving or incomplete")
    token = nonce or secrets.token_hex(16)
    if not isinstance(token, str) or len(token) != 32:
        raise ValueError("permit nonce must be 128-bit hex")
    try:
        bytes.fromhex(token)
    except ValueError as error:
        raise ValueError("permit nonce must be 128-bit hex") from error
    payload = {
        "schema": PERMIT_SCHEMA,
        "prompt": prompt,
        "generation": generation,
        "stream_epoch": stream_epoch,
        "operator_id": operator_id,
        "nonce": token,
        "issued_wall_ns": now,
        "expires_wall_ns": now + PERMIT_TTL_NS,
        "motion": proof,
    }
    signature = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return json.dumps({"payload": payload, "signature": signature},
                      sort_keys=True, separators=(",", ":"))


class PromptPermitVerifier:
    """Fail-closed, prompt/generation-scoped verifier with bounded replay state."""
    def __init__(self, key, *, wall_now_ns=time.time_ns, replay_capacity=1024):
        self.key = bytes(key)
        if len(self.key) < 32:
            raise ValueError("permit verification key must contain at least 32 bytes")
        if type(replay_capacity) is not int or replay_capacity < 1:
            raise ValueError("positive replay capacity required")
        self.wall_now_ns = wall_now_ns
        self.used_nonces = deque(maxlen=replay_capacity)
        self.lock = threading.Lock()

    def verify_and_consume(self, token, *, prompt, generation, stream_epoch):
        try:
            envelope = json.loads(token)
            payload, signature = envelope["payload"], envelope["signature"]
            if set(envelope) != {"payload", "signature"} or not isinstance(payload, dict):
                raise ValueError("permit envelope")
            expected = hmac.new(self.key, _canonical(payload), hashlib.sha256).hexdigest()
            if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
                raise ValueError("permit signature")
            now = self.wall_now_ns()
            if payload.get("schema") != PERMIT_SCHEMA or payload.get("prompt") != prompt:
                raise ValueError("permit scope")
            if type(payload.get("generation")) is not int or payload["generation"] != generation:
                raise ValueError("permit generation")
            if payload.get("stream_epoch") != stream_epoch:
                raise ValueError("permit stream epoch")
            operator_id, nonce = payload.get("operator_id"), payload.get("nonce")
            if not isinstance(operator_id, str) or not 1 <= len(operator_id) <= 128:
                raise ValueError("permit operator")
            if not isinstance(nonce, str) or len(nonce) != 32:
                raise ValueError("permit nonce")
            bytes.fromhex(nonce)
            issued, expires = payload.get("issued_wall_ns"), payload.get("expires_wall_ns")
            if type(issued) is not int or type(expires) is not int:
                raise ValueError("permit time")
            if not 0 <= now - issued <= PERMIT_TTL_NS or expires != issued + PERMIT_TTL_NS or now > expires:
                raise ValueError("permit expired or not yet valid")
            if not _valid_motion_proof(payload.get("motion"), issued):
                raise ValueError("permit motion proof")
            with self.lock:
                if nonce in self.used_nonces:
                    raise ValueError("permit replay")
                self.used_nonces.append(nonce)
            return payload
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise PermissionError(f"invalid prompt transition permit: {error}") from error
