def test_all_nine_packages_import():
    import sandbox  # noqa: F401


def test_trace_id_is_unique():
    from logging_config import new_trace_id
    assert new_trace_id() != new_trace_id()


def test_stage_span_logs_success(capsys):
    from logging_config import configure_logging, new_trace_id, stage_span
    configure_logging()
    tid = new_trace_id()
    with stage_span("test_stage", tid):
        pass
    out = capsys.readouterr().out
    assert '"stage_start"' in out or "stage_start" in out
    assert tid in out
