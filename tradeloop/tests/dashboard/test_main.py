import pytest

from tradeloop.dashboard import __main__ as dashboard_main


def test_parse_args_defaults_to_8770(monkeypatch):
    monkeypatch.delenv("TRADELOOP_DASHBOARD_PORT", raising=False)

    args = dashboard_main.parse_args([])

    assert args.port == 8770


def test_parse_args_reads_port_from_env(monkeypatch):
    monkeypatch.setenv("TRADELOOP_DASHBOARD_PORT", "8771")

    args = dashboard_main.parse_args([])

    assert args.port == 8771


def test_parse_args_cli_port_overrides_env(monkeypatch):
    monkeypatch.setenv("TRADELOOP_DASHBOARD_PORT", "8771")

    args = dashboard_main.parse_args(["--port", "8780"])

    assert args.port == 8780


def test_parse_args_rejects_invalid_env_port(monkeypatch):
    monkeypatch.setenv("TRADELOOP_DASHBOARD_PORT", "not-a-port")

    with pytest.raises(SystemExit):
        dashboard_main.parse_args([])


def test_parse_args_cli_port_ignores_invalid_env(monkeypatch):
    monkeypatch.setenv("TRADELOOP_DASHBOARD_PORT", "not-a-port")
    args = dashboard_main.parse_args(["--port", "8780"])

    assert args.port == 8780
