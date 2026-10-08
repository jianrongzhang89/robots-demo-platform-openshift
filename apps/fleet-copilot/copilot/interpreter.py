from __future__ import annotations

from .catalog import Catalog
from .contracts import ContractError, Preview
from .providers import Provider, ProviderError
from .validator import validate_intent


def interpret(text: str, catalog: Catalog, provider: Provider) -> Preview:
    if not text.strip():
        return Preview("clarify", False, catalog_version=catalog.version, clarification="Enter a fleet request.", provider=provider.name)
    try:
        intent = provider.interpret(text)
        from .contracts import Intent

        return validate_intent(Intent.from_provider(intent), catalog, provider.name)
    except ProviderError as exc:
        return Preview("unsupported", False, catalog_version=catalog.version, reason=f"model error ({exc.code}): {exc}", provider=provider.name)
    except (ContractError, ValueError) as exc:
        return Preview("unsupported", False, catalog_version=catalog.version, reason=f"invalid model output: {exc}", provider=provider.name)
