from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, request


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Provider(Protocol):
    name: str

    def interpret(self, text: str) -> dict[str, Any]: ...


@dataclass
class MockProvider:
    """Deterministic provider for fixtures; it never has dispatch authority."""

    name: str = "mock"

    def interpret(self, text: str) -> dict[str, Any]:
        value = " ".join(text.lower().strip().split())
        if any(term in value for term in ("pickup", "delivery", "package", "charge the battery")):
            return {"action": "unsupported", "reason": "pickup, delivery, and charging are not supported"}
        if any(term in value for term in ("what destinations", "which destinations", "where can", "available places")):
            return {"action": "list_destinations"}
        if any(term in value for term in ("fourth floor", "fifth floor", "l4", "l5", "room 999")):
            return {"action": "unsupported", "reason": "the requested destination is not in the approved catalog"}
        if "lobby" in value or "first floor" in value or "ground floor" in value:
            if any(term in value for term in ("third floor", "level 3", "l3", "middle hallway", "hallway")):
                return {
                    "action": "propose_patrol",
                    "places": ["lobby", "L3_middle_hallway", "lobby"],
                    "rounds": 1,
                }
        if any(term in value for term in ("send", "go", "take", "navigate", "patrol")):
            return {"action": "clarify", "clarification": "Which approved destination should the robot visit?"}
        return {"action": "clarify", "clarification": "Please name an approved hotel destination and route."}


class OpenAIProvider:
    name = "openai-chat-completions"

    def __init__(self, api_key: str | None = None, model: str | None = None, endpoint: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get("FLEET_COPILOT_MODEL", "gpt-4.1-mini-2025-04-14")
        self.endpoint = endpoint or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.last_latency_seconds: float | None = None
        self.last_usage: dict[str, int] | None = None

    def interpret(self, text: str) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("unavailable", "OPENAI_API_KEY is not configured")
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["propose_patrol", "list_destinations", "clarify", "unsupported"]},
                "places": {"type": ["array", "null"], "items": {"type": "string"}},
                "rounds": {"type": ["integer", "null"]},
                "clarification": {"type": ["string", "null"]},
                "reason": {"type": ["string", "null"]},
            },
            "required": ["action", "places", "rounds", "clarification", "reason"],
        }
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Resolve hotel fleet requests into the closed intent schema. "
                        "The only canonical destinations are lobby and L3_middle_hallway. "
                        "Map entrance, ground floor, first floor, and lobby to lobby. "
                        "Map third-floor middle hallway, third floor hallway, level 3 middle hallway, "
                        "middle hallway, L3, and level 3 to L3_middle_hallway. "
                        "For every propose_patrol action, rounds MUST be 1; never return 0 or null. "
                        "For a request to go from the lobby to level 3 and return, places MUST be "
                        "['lobby', 'L3_middle_hallway', 'lobby'] and rounds MUST be 1. "
                        "Words such as return, back, come back, or bring it back require the final lobby. "
                        "Pickup, delivery, package, charging, or an invented floor must be unsupported. "
                        "Never use an alias or free-form phrase in places, never infer rounds from an ID, "
                        "and never invent destinations."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_schema", "json_schema": {"name": "fleet_intent", "strict": True, "schema": schema}},
        }
        req = request.Request(
            self.endpoint.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        self.last_usage = None
        try:
            with request.urlopen(req, timeout=15) as response:
                body = json.loads(response.read())
        except error.HTTPError as exc:
            code = "rate_limited" if exc.code == 429 else "provider_error"
            raise ProviderError(code, f"provider returned HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise ProviderError("timeout", "provider timed out") from exc
        except error.URLError as exc:
            raise ProviderError("unavailable", "provider is unavailable") from exc
        finally:
            self.last_latency_seconds = time.perf_counter() - started
        usage = body.get("usage")
        if isinstance(usage, dict):
            self.last_usage = {
                key: usage[key]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage.get(key), int)
            }
        try:
            message = body["choices"][0]["message"]
            if message.get("refusal"):
                raise ProviderError("refusal", "provider refused the request")
            content = message["content"]
            return json.loads(content)
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("invalid_output", "provider returned incomplete or invalid JSON") from exc
