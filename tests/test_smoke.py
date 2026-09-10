import pytest


def test_all_nine_packages_import():
    import ast_
    import cag
    import codegen
    import confirm
    import dag
    import graph_eng
    import ir
    import nlu
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


def test_missing_required_config_fails_fast(monkeypatch, tmp_path):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.chdir(tmp_path)  # no .env.dev here, so nothing can supply the key

    with pytest.raises(SystemExit):
        get_settings()
