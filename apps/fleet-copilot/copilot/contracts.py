from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_ACTIONS = {"propose_patrol", "list_destinations", "clarify", "unsupported"}


class ContractError(ValueError):
    """Raised when provider output is not a closed, valid intent object."""


@dataclass(frozen=True)
class Intent:
    action: str
    places: tuple[str, ...] = ()
    rounds: int | None = None
    clarification: str | None = None
    reason: str | None = None

    @classmethod
    def from_provider(cls, value: Any) -> "Intent":
        if not isinstance(value, dict):
            raise ContractError("intent must be an object")
        allowed = {"action", "places", "rounds", "clarification", "reason"}
        unknown = set(value) - allowed
        if unknown:
            raise ContractError(f"unknown intent fields: {sorted(unknown)}")
        action = value.get("action")
        if not isinstance(action, str) or action not in SUPPORTED_ACTIONS:
            raise ContractError("action is not supported")
        places = value.get("places", [])
        if places is None:
            places = []
        if not isinstance(places, list) or not all(isinstance(p, str) for p in places):
            raise ContractError("places must be a string array")
        rounds = value.get("rounds")
        if rounds is not None and (isinstance(rounds, bool) or not isinstance(rounds, int)):
            raise ContractError("rounds must be an integer or null")
        for key in ("clarification", "reason"):
            item = value.get(key)
            if item is not None and not isinstance(item, str):
                raise ContractError(f"{key} must be a string or null")
        return cls(action, tuple(places), rounds, value.get("clarification"), value.get("reason"))


@dataclass(frozen=True)
class Preview:
    action: str
    dispatchable: bool
    places: tuple[str, ...] = ()
    rounds: int | None = None
    catalog_version: str | None = None
    clarification: str | None = None
    reason: str | None = None
    errors: tuple[str, ...] = ()
    provider: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "dispatchable": self.dispatchable,
            "places": list(self.places),
            "rounds": self.rounds,
            "catalog_version": self.catalog_version,
            "clarification": self.clarification,
            "reason": self.reason,
            "errors": list(self.errors),
            "provider": self.provider,
        }
