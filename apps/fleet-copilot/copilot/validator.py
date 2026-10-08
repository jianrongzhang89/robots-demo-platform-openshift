from __future__ import annotations

from .catalog import Catalog
from .contracts import ContractError, Intent, Preview


def validate_intent(intent: Intent, catalog: Catalog, provider: str) -> Preview:
    if intent.action == "list_destinations":
        return Preview(
            intent.action,
            False,
            tuple(place.name for place in catalog.places),
            catalog_version=catalog.version,
            provider=provider,
        )
    if intent.action in {"clarify", "unsupported"}:
        return Preview(
            intent.action,
            False,
            catalog_version=catalog.version,
            clarification=intent.clarification,
            reason=intent.reason,
            provider=provider,
        )
    if intent.action != "propose_patrol":
        raise ContractError("intent action cannot be executed")

    errors: list[str] = []
    if intent.rounds != 1:
        errors.append("only one patrol round is supported in phase 1")
    if not 2 <= len(intent.places) <= 8:
        errors.append("patrol must contain between 2 and 8 places")
    canonical_places = tuple(catalog.resolve(place) or place for place in intent.places)
    unknown = [place for place in canonical_places if not catalog.contains(place)]
    if unknown:
        errors.append("unknown destination(s): " + ", ".join(unknown))
    return Preview(
        intent.action,
        not errors,
        canonical_places,
        intent.rounds,
        catalog.version,
        reason="; ".join(errors) if errors else None,
        errors=tuple(errors),
        provider=provider,
    )
