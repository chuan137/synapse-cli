import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import click
from jinja2 import Template

from synapse.db import init_db

DEFAULT_ROLES = (
    "agent_a = Architect (review, audit, design)\n"
    "agent_b = Developer (implementation, execution)"
)


def find_synapse_root(start: Path | None = None) -> Path | None:
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".synapse").is_dir():
            return parent
    return None


def require_synapse_root() -> tuple[Path, Path]:
    root = find_synapse_root()
    if root is None:
        click.echo("error: no .synapse/ directory found. Run `synapse init` first.", err=True)
        sys.exit(1)
    return root, root / ".synapse"


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_services(synapse_dir: Path) -> None:
    for pid_file in sorted((synapse_dir / "pids").glob("*.pid")):
        pid = _read_pid(pid_file)
        if pid and _is_running(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        pid_file.unlink(missing_ok=True)

    db_path = synapse_dir / "synapse.db"
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE agent_status SET state = 'offline', updated_at = CURRENT_TIMESTAMP"
            )


def _heartbeat_age(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        if age < 60:
            return f"{int(age)}s ago"
        if age < 3600:
            return f"{int(age / 60)}m ago"
        return f"{int(age / 3600)}h ago"
    except ValueError:
        return ts


@click.group()
def cli():
    """Synapse — multi-agent governance CLI."""


@cli.command()
@click.option(
    "--roles",
    default=DEFAULT_ROLES,
    show_default=True,
    help="Agent roles description written into CLAUDE.md (replaces {{AGENT_ROLES}}).",
)
@click.option("--port", default=8765, show_default=True, help="Port for S-Deck dashboard.")
def init(roles: str, port: int) -> None:
    """Initialize Synapse in the current project directory."""
    project_root = Path.cwd()
    synapse_dir = project_root / ".synapse"

    if synapse_dir.exists():
        click.echo("error: already initialized. Run `synapse destroy` first to reinitialize.", err=True)
        sys.exit(1)

    (synapse_dir / "logs").mkdir(parents=True)
    (synapse_dir / "pids").mkdir(parents=True)

    init_db(synapse_dir / "synapse.db")

    config = {
        "port": port,
        "agent_ids": ["agent_a", "agent_b"],
        "workflow": "",
        "agent_roles_description": roles,
    }
    (synapse_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    template_text = (
        files("synapse.templates")
        .joinpath("CLAUDE.project.md")
        .read_text(encoding="utf-8")
    )
    rendered = Template(template_text).render(AGENT_ROLES=roles)
    (project_root / "CLAUDE.md").write_text(rendered, encoding="utf-8")

    subprocess.run(
        [
            "claude", "mcp", "add", "synapse-bus",
            "--scope", "project",
            "--",
            "synapse-mcp-server",
            "--synapse-dir", str(synapse_dir.resolve()),
        ],
        check=True,
    )

    click.echo("✓ Synapse initialized.")
    click.echo(f"  .synapse/  → {synapse_dir}")
    click.echo(f"  CLAUDE.md  → {project_root / 'CLAUDE.md'}")
    click.echo("  MCP        → synapse-bus (project scope)")
    click.echo("\nRun `synapse start` to launch S-Deck.")


@cli.command()
def start() -> None:
    """Start the S-Deck dashboard."""
    _root, synapse_dir = require_synapse_root()

    deck_pid_file = synapse_dir / "pids" / "deck.pid"
    pid = _read_pid(deck_pid_file)
    if pid and _is_running(pid):
        click.echo(f"error: S-Deck is already running (pid {pid}).", err=True)
        sys.exit(1)

    config = json.loads((synapse_dir / "config.json").read_text())
    port = config["port"]
    log_path = synapse_dir / "logs" / "deck.log"

    with open(log_path, "a") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "synapse.deck:app",
             "--host", "127.0.0.1", "--port", str(port)],
            env={**os.environ, "SYNAPSE_DIR": str(synapse_dir)},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    deck_pid_file.write_text(str(proc.pid))
    click.echo(f"✓ S-Deck started (pid {proc.pid}) → http://localhost:{port}")
    click.echo(f"  Logs → {log_path}")


@cli.command()
def stop() -> None:
    """Stop the S-Deck dashboard and mark agents offline."""
    _root, synapse_dir = require_synapse_root()

    pids_dir = synapse_dir / "pids"
    pid_files = sorted(pids_dir.glob("*.pid"))

    if not pid_files:
        click.echo("Nothing is running.")
        return

    for pid_file in pid_files:
        pid = _read_pid(pid_file)
        if pid is None:
            pid_file.unlink(missing_ok=True)
            continue
        if _is_running(pid):
            os.kill(pid, signal.SIGTERM)
            click.echo(f"  Stopped {pid_file.stem} (pid {pid})")
        else:
            click.echo(f"  {pid_file.stem} was not running (stale pid {pid})")
        pid_file.unlink(missing_ok=True)

    with sqlite3.connect(synapse_dir / "synapse.db") as conn:
        conn.execute(
            "UPDATE agent_status SET state = 'offline', updated_at = CURRENT_TIMESTAMP"
        )

    click.echo("✓ Stopped.")


@cli.command()
def status() -> None:
    """Show agent status and service health."""
    _root, synapse_dir = require_synapse_root()

    config = json.loads((synapse_dir / "config.json").read_text())
    port = config["port"]

    deck_pid_file = synapse_dir / "pids" / "deck.pid"
    pid = _read_pid(deck_pid_file)
    if pid and _is_running(pid):
        deck_line = f"running   pid={pid}  http://localhost:{port}"
    elif pid:
        deck_line = f"dead      stale pid={pid}"
    else:
        deck_line = "stopped"

    click.echo(f"S-Deck   {deck_line}")
    click.echo("")

    with sqlite3.connect(synapse_dir / "synapse.db") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM agent_status ORDER BY agent_id").fetchall()

    if not rows:
        click.echo("No agents registered yet.")
        return

    click.echo(f"{'AGENT':<12} {'STATE':<10} {'TURNS':>5}  {'HEARTBEAT':<14}  TASK")
    click.echo("-" * 72)
    for r in rows:
        hb = _heartbeat_age(r["last_heartbeat"])
        task = r["current_task"] or "-"
        turns = r["context_turns"] or 0
        click.echo(f"{r['agent_id']:<12} {r['state']:<10} {turns:>5}  {hb:<14}  {task}")


@cli.command()
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def destroy(yes: bool) -> None:
    """Stop services, remove .synapse/, and unregister MCP."""
    _root, synapse_dir = require_synapse_root()

    if not yes:
        click.confirm(
            f"Remove {synapse_dir} and unregister MCP server?", abort=True
        )

    _stop_services(synapse_dir)

    subprocess.run(
        ["claude", "mcp", "remove", "synapse-bus", "--scope", "project"],
        check=False,
    )

    shutil.rmtree(synapse_dir)
    click.echo("✓ Synapse destroyed.")
