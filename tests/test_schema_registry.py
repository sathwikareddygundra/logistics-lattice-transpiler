from unittest.mock import patch

import pytest

from schemas.canonical import Shipment, TrackingEvent, TurnaroundRecord
from schemas.registry import (
    SchemaRegistry,
    UnknownSchemaVersionError,
    UnknownSourceError,
)


def test_load_returns_canonical_dispatch_schema() -> None:
    registry = SchemaRegistry()
    assert registry.load("dispatch", "v1") is Shipment


def test_load_returns_canonical_tracking_schema() -> None:
    registry = SchemaRegistry()
    assert registry.load("tracking", "v1") is TrackingEvent


def test_load_returns_canonical_turnaround_schema() -> None:
    registry = SchemaRegistry()
    assert registry.load("turnaround_time", "v1") is TurnaroundRecord


def test_second_load_uses_cache_not_underlying_resolve() -> None:
    registry = SchemaRegistry()
    with patch.object(registry, "_resolve", wraps=registry._resolve) as spy:
        registry.load("dispatch", "v1")
        registry.load("dispatch", "v1")
        assert spy.call_count == 1


def test_different_source_version_pairs_cache_independently() -> None:
    registry = SchemaRegistry()
    with patch.object(registry, "_resolve", wraps=registry._resolve) as spy:
        registry.load("dispatch", "v1")
        registry.load("tracking", "v1")
        registry.load("dispatch", "v1")  # cache hit, no new _resolve call
        assert spy.call_count == 2


def test_unknown_source_raises() -> None:
    registry = SchemaRegistry()
    with pytest.raises(UnknownSourceError):
        registry.load("UNKNOWN", "v1")


def test_unknown_version_raises() -> None:
    registry = SchemaRegistry()
    with pytest.raises(UnknownSchemaVersionError):
        registry.load("dispatch", "v999")
