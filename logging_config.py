import logging
import sys
import time
import uuid
from contextlib import contextmanager

import structlog


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


@contextmanager
def stage_span(stage_name: str, trace_id: str, **extra):
    start = time.perf_counter()
    log.info("stage_start", stage=stage_name, trace_id=trace_id, **extra)
    try:
        yield
    except Exception as e:
        duration = time.perf_counter() - start
        log.error(
            "stage_failed", stage=stage_name, trace_id=trace_id,
            duration_ms=round(duration * 1000, 2), error=str(e),
        )
        raise
    else:
        duration = time.perf_counter() - start
        log.info(
            "stage_success", stage=stage_name, trace_id=trace_id,
            duration_ms=round(duration * 1000, 2),
        )
