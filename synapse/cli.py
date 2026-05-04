import json
import subprocess
import sys
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
    """Walk up from start (default: CWD) to find the nearest .synapse/ directory."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".synapse").is_dir():
            return parent
    return None


def require_synapse_root() -> tuple[Path, Path]:
    """Return (project_root, synapse_dir) or exit with an error."""
    root = find_synapse_root()
    if root is None:
        click.echo("error: no .synapse/ directory found. Run `synapse init` first.", err=True)
        sys.exit(1)
    return root, root / ".synapse"


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

    # Directory structure
    (synapse_dir / "logs").mkdir(parents=True)
    (synapse_dir / "pids").mkdir(parents=True)

    # Database
    init_db(synapse_dir / "synapse.db")

    # Config
    config = {
        "port": port,
        "agent_ids": ["agent_a", "agent_b"],
        "workflow": "",
        "agent_roles_description": roles,
    }
    (synapse_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    # CLAUDE.md — rendered from the bundled template
    template_text = (
        files("synapse.templates")
        .joinpath("CLAUDE.project.md")
        .read_text(encoding="utf-8")
    )
    rendered = Template(template_text).render(AGENT_ROLES=roles)
    (project_root / "CLAUDE.md").write_text(rendered, encoding="utf-8")

    # MCP registration
    # synapse-mcp-server is the entry point defined in pyproject.toml;
    # --synapse-dir pins it to this project's .synapse/ at registration time.
    subprocess.run(
        [
            "claude", "mcp", "add", "synapse-bus",
            "--scope", "project",
            "synapse-mcp-server",
            "--synapse-dir", str(synapse_dir.resolve()),
        ],
        check=True,
    )

    click.echo("✓ Synapse initialized.")
    click.echo(f"  .synapse/  → {synapse_dir}")
    click.echo(f"  CLAUDE.md  → {project_root / 'CLAUDE.md'}")
    click.echo("  MCP        → synapse-bus (project scope)")
    click.echo("\nRun `synapse start` to launch S-Deck and the MCP server.")


@cli.command()
def start() -> None:
    """Start the MCP server and S-Deck dashboard."""
    _root, _synapse_dir = require_synapse_root()
    raise NotImplementedError("start: not yet implemented")


@cli.command()
def stop() -> None:
    """Stop the MCP server and S-Deck dashboard."""
    _root, _synapse_dir = require_synapse_root()
    raise NotImplementedError("stop: not yet implemented")


@cli.command()
def status() -> None:
    """Show agent status and service health."""
    _root, _synapse_dir = require_synapse_root()
    raise NotImplementedError("status: not yet implemented")


@cli.command()
def destroy() -> None:
    """Stop services, remove .synapse/, and unregister MCP."""
    _root, _synapse_dir = require_synapse_root()
    raise NotImplementedError("destroy: not yet implemented")
