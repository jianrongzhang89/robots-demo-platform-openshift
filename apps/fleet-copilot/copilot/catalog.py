from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Destination:
    name: str
    floor: str
    aliases: tuple[str, ...]


class Catalog:
    def __init__(self, places: tuple[Destination, ...], version: str):
        self.places = places
        self.version = version
        self._names = {place.name for place in places}
        self._aliases = {
            alias.lower(): place.name
            for place in places
            for alias in (place.name, *place.aliases)
        }

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        version = "sha256:" + hashlib.sha256(canonical).hexdigest()[:16]
        places = tuple(
            Destination(item["name"], item["floor"], tuple(item.get("aliases", [])))
            for item in payload["destinations"]
        )
        if len({place.name for place in places}) != len(places):
            raise ValueError("catalog contains duplicate destination names")
        return cls(places, version)

    def resolve(self, value: str) -> str | None:
        return self._aliases.get(value.strip().lower())

    def contains(self, value: str) -> bool:
        return value in self._names

    def as_dict(self) -> dict:
        return {
            "catalog_version": self.version,
            "destinations": [
                {"name": place.name, "floor": place.floor, "aliases": list(place.aliases)}
                for place in self.places
            ],
        }
