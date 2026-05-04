"""Tests for extra instructions injected at init time and visible to all agents."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from synapse.cli import cli


@pytest.fixture()
def runner():
    return CliRunner()


def _init(tmp_path: Path, monkeypatch, runner, extra: str = "", roles: str = "") -> Path:
    monkeypatch.chdir(tmp_path)
    args = ["init"]
    if extra:
        args += ["--extra", extra]
    if roles:
        args += ["--roles", roles]
    with patch("synapse.cli.subprocess.run"):
        result = runner.invoke(cli, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return tmp_path


# ---------------------------------------------------------------------------
# Extra instructions appear in CLAUDE.md
# ---------------------------------------------------------------------------


def test_extra_instructions_present_in_claude_md(tmp_path, monkeypatch, runner):
    extra = "Always write tests before writing implementation code."
    _init(tmp_path, monkeypatch, runner, extra=extra)
    assert extra in (tmp_path / "CLAUDE.md").read_text()


def test_no_extra_section_when_omitted(tmp_path, monkeypatch, runner):
    _init(tmp_path, monkeypatch, runner)
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "Project-Specific Instructions" not in claude_md


def test_extra_section_heading_appears_when_set(tmp_path, monkeypatch, runner):
    _init(tmp_path, monkeypatch, runner, extra="Use TDD.")
    assert "Project-Specific Instructions" in (tmp_path / "CLAUDE.md").read_text()


def test_extra_instructions_multiline(tmp_path, monkeypatch, runner):
    extra = "Rule 1: write tests first.\nRule 2: never force-push main."
    _init(tmp_path, monkeypatch, runner, extra=extra)
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "Rule 1: write tests first." in claude_md
    assert "Rule 2: never force-push main." in claude_md


# ---------------------------------------------------------------------------
# Both agents share the same CLAUDE.md
# ---------------------------------------------------------------------------


def test_agent_a_sees_extra_instructions(tmp_path, monkeypatch, runner):
    extra = "Prefer small commits."
    _init(tmp_path, monkeypatch, runner, extra=extra)
    # agent_a's identity is established by the roles section in CLAUDE.md
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "agent_a" in claude_md
    assert extra in claude_md


def test_agent_b_sees_extra_instructions(tmp_path, monkeypatch, runner):
    extra = "Prefer small commits."
    _init(tmp_path, monkeypatch, runner, extra=extra)
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "agent_b" in claude_md
    assert extra in claude_md


def test_extra_instructions_appear_after_roles(tmp_path, monkeypatch, runner):
    extra = "Use feature flags for risky changes."
    roles = "agent_a = Reviewer\nagent_b = Coder"
    _init(tmp_path, monkeypatch, runner, extra=extra, roles=roles)
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert claude_md.index(roles) < claude_md.index(extra)


# ---------------------------------------------------------------------------
# Extra instructions are stored in config.json
# ---------------------------------------------------------------------------


def test_extra_instructions_saved_in_config(tmp_path, monkeypatch, runner):
    extra = "Deploy on Fridays only if you enjoy pain."
    _init(tmp_path, monkeypatch, runner, extra=extra)
    config = json.loads((tmp_path / ".synapse" / "config.json").read_text())
    assert config["extra_instructions"] == extra


def test_no_extra_instructions_config_empty_string(tmp_path, monkeypatch, runner):
    _init(tmp_path, monkeypatch, runner)
    config = json.loads((tmp_path / ".synapse" / "config.json").read_text())
    assert config["extra_instructions"] == ""


# ---------------------------------------------------------------------------
# Extra instructions do not bleed between separate projects
# ---------------------------------------------------------------------------


def test_extra_instructions_isolated_between_projects(tmp_path, monkeypatch, runner):
    project_a = tmp_path / "proj_a"
    project_b = tmp_path / "proj_b"
    project_a.mkdir()
    project_b.mkdir()

    extra_a = "Project A only: use React."
    extra_b = "Project B only: use Vue."

    monkeypatch.chdir(project_a)
    with patch("synapse.cli.subprocess.run"):
        runner.invoke(cli, ["init", "--extra", extra_a], catch_exceptions=False)

    monkeypatch.chdir(project_b)
    with patch("synapse.cli.subprocess.run"):
        runner.invoke(cli, ["init", "--extra", extra_b], catch_exceptions=False)

    claude_a = (project_a / "CLAUDE.md").read_text()
    claude_b = (project_b / "CLAUDE.md").read_text()

    assert extra_a in claude_a
    assert extra_b not in claude_a
    assert extra_b in claude_b
    assert extra_a not in claude_b
