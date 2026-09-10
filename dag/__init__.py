from logging_config import stage_span


def run(trace_id: str) -> None:
    with stage_span("dag", trace_id):
        pass  # real logic lands here in a later phase
