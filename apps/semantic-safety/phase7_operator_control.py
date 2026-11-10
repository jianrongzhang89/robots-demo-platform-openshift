"""Fail-closed coordinator for an authenticated Phase 7 prompt change.

The embedding operator endpoint supplies the authenticated request and ROS
callbacks. This core stops/cancels motion, waits on the independent NativeClock,
issues a scoped permit, applies the transition, and returns only after the
adapter reports a fresh matching result. It deliberately does not resume motion.
"""
import hmac
import time

from phase7_prompt_permit import issue_prompt_permit


class PromptTransitionControl:
    def __init__(self, *, clock, approved_prompts, operator_credential,
                 operator_id, signing_key, adapter_status, stop_navigation,
                 apply_prompt, pump, wall_now_ns=time.time_ns,
                 sleep=time.sleep):
        self.clock = clock
        self.approved_prompts = tuple(approved_prompts)
        self.operator_credential = (dict(operator_credential)
            if isinstance(operator_credential, dict) else str(operator_credential))
        self.operator_id = operator_id
        self.signing_key = bytes(signing_key)
        self.adapter_status = adapter_status
        self.stop_navigation = stop_navigation
        self.apply_prompt = apply_prompt
        self.pump = pump
        self.wall_now_ns = wall_now_ns
        self.sleep = sleep

    def transition(self, request, *, timeout_s=10.0):
        if (not isinstance(request, dict) or
                set(request) not in ({"action", "token", "prompt"},
                                    {"action", "token", "prompt", "operator_id"})):
            raise ValueError("prompt request schema is invalid")
        if request["action"] != "change_prompt" or not isinstance(request["token"], str):
            raise PermissionError("authenticated prompt-change request required")
        request_operator = request.get("operator_id")
        if request_operator is not None and (
                not isinstance(request_operator, str) or
                not 1 <= len(request_operator) <= 128):
            raise ValueError("bounded authenticated operator identity required")
        credential = self.operator_credential
        if isinstance(credential, dict):
            if (not isinstance(request_operator, str) or
                    request_operator not in credential):
                raise PermissionError("operator authorization failed")
            expected_credential = credential[request_operator]
        else:
            expected_credential = credential
        if not hmac.compare_digest(request["token"], expected_credential):
            raise PermissionError("operator authorization failed")
        prompt = request["prompt"]
        if not isinstance(prompt, str) or prompt not in self.approved_prompts:
            raise ValueError("prompt is not approved")
        if type(timeout_s) not in (float, int) or not 0 < timeout_s <= 60:
            raise ValueError("prompt-transition timeout outside bound")

        initial = self.adapter_status() or {}
        generation = initial.get("policy_generation")
        stream_epoch = initial.get("stream_epoch")
        current_prompt = initial.get("prompt")
        if (initial.get("ready") is not True or
                initial.get("prompt_transition_ready") is not True or
                type(generation) is not int or generation < 1 or
                not isinstance(stream_epoch, str) or not stream_epoch or
                not isinstance(current_prompt, str)):
            raise RuntimeError("adapter must be ready before prompt transition")
        if prompt == current_prompt:
            return {"prompt": prompt, "generation": generation,
                    "stream_epoch": stream_epoch, "changed": False}

        if self.stop_navigation() is not True:
            raise RuntimeError("navigation stop/cancel was not confirmed")
        deadline = time.monotonic() + timeout_s
        while not self.clock.stationary(self.wall_now_ns()):
            self.pump()
            if self.clock.fault:
                raise RuntimeError(f"native motion evidence fault: {self.clock.fault}")
            if time.monotonic() >= deadline:
                raise TimeoutError("native motion did not become stationary")
            self.sleep(.01)

        next_generation = generation + 1
        permit_clock = (self.clock.snapshot() if callable(
            getattr(self.clock, "snapshot", None)) else self.clock)
        permit = issue_prompt_permit(
            prompt=prompt, generation=next_generation, stream_epoch=stream_epoch,
            approved_prompts=self.approved_prompts,
            operator_credential=request["token"],
            expected_operator_credential=expected_credential,
            operator_id=(request_operator if request_operator is not None
                         else self.operator_id), clock=permit_clock,
            key=self.signing_key, now_wall_ns=self.wall_now_ns())
        if self.apply_prompt(prompt, permit) is not True:
            raise RuntimeError("adapter rejected the signed prompt transition")

        while time.monotonic() < deadline:
            self.pump()
            if not self.clock.stationary(self.wall_now_ns()):
                raise RuntimeError("motion-stop proof was lost during prompt transition")
            state = self.adapter_status() or {}
            if (state.get("prompt") == prompt and
                    state.get("policy_generation") == next_generation and
                    state.get("prompt_transition_ready") is True and
                    state.get("ready") is True):
                return {"prompt": prompt, "generation": next_generation,
                        "stream_epoch": state.get("stream_epoch"),
                        "changed": True, "resumed": False}
            self.sleep(.01)
        raise TimeoutError("adapter did not publish a fresh result for the new generation")
