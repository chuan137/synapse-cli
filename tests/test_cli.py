"""Functional tests for the synapse CLI (init, start, stop, status, destroy)."""

import json
import os
import signal
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from synapse.cli import cli
from synapse.db import init_db


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def project(tmp_path: Path, monkeypatch) -> Path:
    """An initialised project directory with .synapse/ already in place."""
    monkeypatch.chdir(tmp_path)
    synapse_dir = tmp_path / ".synapse"
    (synapse_dir / "logs").mkdir(parents=True)
    (synapse_dir / "pids").mkdir()
    init_db(synapse_dir / "synapse.db")
    config = {
        "port": 8765,
        "agent_ids": ["agent_a", "agent_b"],
        "workflow": "",
        "agent_roles_description": "agent_a = Architect\nagent_b = Developer",
    }
    (synapse_dir / "config.json").write_text(json.dumps(config))
    return tmp_path


def _db(project: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(project / ".synapse" / "synapse.db")
    conn.row_factory = sqlite3.Row
    return conn


def _seed_agent(project: Path, agent_id: str = "agent_a", state: str = "idle") -> None:
    with _db(project) as conn:
        conn.execute(
            "INSERT INTO agent_status (agent_id, state, current_task, context_turns, last_heartbeat)"
            " VALUES (?, ?, 'test task', 3, CURRENT_TIMESTAMP)",
            (agent_id, state),
        )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_directory_structure(tmp_path: Path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)
    with patch("synapse.cli.subprocess.run"):
        result = runner.invoke(cli, ["init"], catch_exceptions=False)

    assert result.exit_code == 0
    sd = tmp_path / ".synapse"
    assert (sd / "logs").is_dir()
    assert (sd / "pids").is_dir()
    assert (sd / "synapse.db").is_file()
    assert (sd / "config.json").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()


def test_init_config_values(tmp_path: Path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)
    with patch("synapse.cli.subprocess.run"):
        runner.invoke(cli, ["init", "--port", "9000"], catch_exceptions=False)

    config = json.loads((tmp_path / ".synapse" / "config.json").read_text())
    assert config["port"] == 9000
    assert config["agent_ids"] == ["agent_a", "agent_b"]


def test_init_renders_roles_into_claude_md(tmp_path: Path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)
    with patch("synapse.cli.subprocess.run"):
        runner.invoke(
            cli, ["init", "--roles", "agent_a = Tester\nagent_b = Builder"],
            catch_exceptions=False,
        )

    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "agent_a = Tester" in claude_md
    assert "agent_b = Builder" in claude_md


def test_init_registers_mcp(tmp_path: Path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)
    with patch("synapse.cli.subprocess.run") as mock_run:
        runner.invoke(cli, ["init"], catch_exceptions=False)

    call_args = mock_run.call_args[0][0]
    assert "claude" in call_args
    assert "mcp" in call_args
    assert "add" in call_args
    assert "synapse-bus" in call_args
    assert "--synapse-dir" in call_args


def test_init_fails_if_already_initialized(project: Path, runner):
    result = runner.invoke(cli, ["init"])
    assert result.exit_code != 0
    assert "already initialized" in result.output


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_writes_pid_file(project: Path, runner):
    mock_proc = MagicMock()
    mock_proc.pid = 99999

    with patch("synapse.cli.subprocess.Popen", return_value=mock_proc):
        result = runner.invoke(cli, ["start"], catch_exceptions=False)

    assert result.exit_code == 0
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    assert pid_file.exists()
    assert pid_file.read_text().strip() == "99999"


def test_start_launches_uvicorn_with_synapse_dir_env(project: Path, runner):
    mock_proc = MagicMock()
    mock_proc.pid = 99999

    with patch("synapse.cli.subprocess.Popen", return_value=mock_proc) as mock_popen:
        runner.invoke(cli, ["start"], catch_exceptions=False)

    _, kwargs = mock_popen.call_args
    assert "SYNAPSE_DIR" in kwargs["env"]
    assert kwargs["env"]["SYNAPSE_DIR"] == str(project / ".synapse")


def test_start_fails_if_already_running(project: Path, runner):
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    pid_file.write_text(str(os.getpid()))  # use test process PID — guaranteed alive

    result = runner.invoke(cli, ["start"])
    assert result.exit_code != 0
    assert "already running" in result.output


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_sigterms_running_process(project: Path, runner):
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    pid_file.write_text("12345")

    with patch("synapse.cli.os.kill") as mock_kill, \
         patch("synapse.cli._is_running", return_value=True):
        result = runner.invoke(cli, ["stop"], catch_exceptions=False)

    assert result.exit_code == 0
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    assert not pid_file.exists()


def test_stop_removes_stale_pid_file(project: Path, runner):
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    pid_file.write_text("99999")

    with patch("synapse.cli._is_running", return_value=False):
        result = runner.invoke(cli, ["stop"], catch_exceptions=False)

    assert result.exit_code == 0
    assert not pid_file.exists()
    assert "not running" in result.output


def test_stop_marks_agents_offline(project: Path, runner):
    _seed_agent(project, "agent_a", state="working")
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    pid_file.write_text("12345")

    with patch("synapse.cli.os.kill"), \
         patch("synapse.cli._is_running", return_value=True):
        runner.invoke(cli, ["stop"], catch_exceptions=False)

    with _db(project) as conn:
        row = conn.execute("SELECT state FROM agent_status WHERE agent_id = 'agent_a'").fetchone()
    assert row["state"] == "offline"


def test_stop_when_nothing_running(project: Path, runner):
    result = runner.invoke(cli, ["stop"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Nothing" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_shows_deck_stopped(project: Path, runner):
    result = runner.invoke(cli, ["status"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "stopped" in result.output


def test_status_shows_deck_running(project: Path, runner):
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    pid_file.write_text(str(os.getpid()))  # test process is alive

    result = runner.invoke(cli, ["status"], catch_exceptions=False)
    assert "running" in result.output
    assert "localhost:8765" in result.output


def test_status_shows_agent_table(project: Path, runner):
    _seed_agent(project, "agent_a", state="idle")

    result = runner.invoke(cli, ["status"], catch_exceptions=False)
    assert "agent_a" in result.output
    assert "idle" in result.output
    assert "test task" in result.output


def test_status_no_agents_message(project: Path, runner):
    result = runner.invoke(cli, ["status"], catch_exceptions=False)
    assert "No agents registered" in result.output


def test_status_outside_project_exits(tmp_path: Path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["status"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------


def test_destroy_removes_synapse_dir(project: Path, runner):
    with patch("synapse.cli.subprocess.run"):
        result = runner.invoke(cli, ["destroy", "--yes"], catch_exceptions=False)

    assert result.exit_code == 0
    assert not (project / ".synapse").exists()


def test_destroy_calls_mcp_remove(project: Path, runner):
    with patch("synapse.cli.subprocess.run") as mock_run:
        runner.invoke(cli, ["destroy", "--yes"], catch_exceptions=False)

    call_args = mock_run.call_args[0][0]
    assert "claude" in call_args
    assert "mcp" in call_args
    assert "remove" in call_args
    assert "synapse-bus" in call_args


def test_destroy_stops_running_services(project: Path, runner):
    pid_file = project / ".synapse" / "pids" / "deck.pid"
    pid_file.write_text("12345")

    with patch("synapse.cli.subprocess.run"), \
         patch("synapse.cli.os.kill") as mock_kill, \
         patch("synapse.cli._is_running", return_value=True):
        runner.invoke(cli, ["destroy", "--yes"], catch_exceptions=False)

    mock_kill.assert_called_once_with(12345, signal.SIGTERM)


def test_destroy_prompts_without_yes(project: Path, runner):
    result = runner.invoke(cli, ["destroy"], input="n\n")
    assert result.exit_code != 0
    assert (project / ".synapse").exists()
