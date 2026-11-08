import logging
import resource
import sys
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager

import structlog

from ops import metrics


def configure_logging(level=logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()


def new_trace_id() -> str:
    return str(uuid.uuid4())


_TRACES: OrderedDict[str, list[dict]] = OrderedDict()
_TRACE_LOCK = threading.Lock()
MAX_TRACES = 500


def _record(trace_id: str, event: dict) -> None:
    with _TRACE_LOCK:
        _TRACES.setdefault(trace_id, []).append(event)
        _TRACES.move_to_end(trace_id)
        while len(_TRACES) > MAX_TRACES:
            _TRACES.popitem(last=False)


def get_trace(trace_id: str) -> list[dict]:
    """One query's whole journey, chronological, JSON-serializable (T-87)."""
    with _TRACE_LOCK:
        return list(_TRACES.get(trace_id, []))


def clear_traces() -> None:
    with _TRACE_LOCK:
        _TRACES.clear()


@contextmanager
def stage_span(stage_name: str, trace_id: str, **extra):
    start = time.perf_counter()
    cpu_start = time.process_time()
    started_at = time.time()
    log.info("stage_start", stage=stage_name, trace_id=trace_id, **extra)

    def event(ok: bool, error: str = "") -> dict:
        return {
            "stage": stage_name,
            "trace_id": trace_id,
            "ts": started_at,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            "cpu_ms": round((time.process_time() - cpu_start) * 1000, 2),
            "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "ok": ok,
            "error": error,
            **{k: str(v) for k, v in extra.items()},
        }

    try:
        yield
    except Exception as e:
        ev = event(False, str(e))
        _record(trace_id, ev)
        log.error(
            "stage_failed",
            stage=stage_name,
            trace_id=trace_id,
            duration_ms=ev["duration_ms"],
            error=str(e),
        )
        raise
    else:
        ev = event(True)
        _record(trace_id, ev)
        metrics.REGISTRY.observe_stage(stage_name, ev["duration_ms"])
        log.info(
            "stage_success",
            stage=stage_name,
            trace_id=trace_id,
            duration_ms=ev["duration_ms"],
        )
