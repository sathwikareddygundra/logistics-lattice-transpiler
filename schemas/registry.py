"""T-11: Schema Registry — the single canonical access point for schemas.

Wraps T-10's canonical models (schemas/canonical.py) rather than defining
a second schema representation. This registry's only job is: resolve a
(source, version) pair to the matching T-10 pydantic model, validate
that pair against the T-9 schema documents on disk, and cache results so
repeated lookups don't re-read from disk.

Naming note: the original T-11 spec used "plant" (e.g. load("MCW", "v3")),
from a build-guide scenario with multiple named plant databases. This
project's actual data isn't plant-scoped — it's three fixed sources
profiled directly from the uploaded CSVs. "plant" is renamed "source"
to match what actually exists in this repo, not a fictional dataset.

Versioning note: T-10 currently defines exactly one version of each
schema. "version" is kept as a real, checked parameter so the registry
doesn't need a redesign once a schema actually changes — but "v1" is
the only valid version for any source right now.
"""
from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from schemas.canonical import Shipment, TrackingEvent, TurnaroundRecord

_SCHEMAS_DIR = Path(__file__).parent
_CURRENT_VERSION = "v1"

SchemaClass = type[Shipment] | type[TrackingEvent] | type[TurnaroundRecord]


class Source(StrEnum):
    """The three T-9/T-10 canonical sources."""

    DISPATCH = "dispatch"
    TRACKING = "tracking"
    TURNAROUND_TIME = "turnaround_time"


_SCHEMA_CLASSES: dict[Source, SchemaClass] = {
    Source.DISPATCH: Shipment,
    Source.TRACKING: TrackingEvent,
    Source.TURNAROUND_TIME: TurnaroundRecord,
}

# T-9's schema documents on disk — reused here to validate a lookup
# actually corresponds to a real, previously inventoried source.
_SCHEMA_DOC_FILENAMES: dict[Source, str] = {
    Source.DISPATCH: "dispatch.json",
    Source.TRACKING: "tracking.json",
    Source.TURNAROUND_TIME: "turnaround_time.json",
}


class UnknownSourceError(KeyError):
    """Raised when `source` isn't one of the sources T-9/T-10 defined."""


class UnknownSchemaVersionError(KeyError):
    """Raised when `version` isn't a version this source currently has."""


class SchemaRegistry:
    """Single canonical access point for schemas.

    Usage:
        registry = SchemaRegistry()
        Shipment = registry.load("dispatch", "v1")
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], SchemaClass] = {}

    def load(self, source: str, version: str) -> SchemaClass:
        cache_key = (source, version)
        if cache_key in self._cache:
            return self._cache[cache_key]

        schema = self._resolve(source, version)
        self._cache[cache_key] = schema
        return schema

    def _resolve(self, source: str, version: str) -> SchemaClass:
        """The actual (cacheable) lookup. Kept separate from `load` so
        tests can spy on this method to verify caching behavior."""
        try:
            resolved_source = Source(source)
        except ValueError as exc:
            raise UnknownSourceError(
                f"Unknown schema source: {source!r}. "
                f"Known sources: {[s.value for s in Source]}"
            ) from exc

        if version != _CURRENT_VERSION:
            raise UnknownSchemaVersionError(
                f"Unknown schema version {version!r} for source {source!r}. "
                f"Known versions: ['{_CURRENT_VERSION}']"
            )

        doc_path = _SCHEMAS_DIR / _SCHEMA_DOC_FILENAMES[resolved_source]
        with doc_path.open() as f:
            json.load(f)  # confirms T-9's schema document genuinely exists

        return _SCHEMA_CLASSES[resolved_source]
