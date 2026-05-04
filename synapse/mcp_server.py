import json
import logging
import sqlite3
from pathlib import Path

import click
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("synapse-bus")
_db_path: Path | None = None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def read_messages(agent_id: str) -> str:
    """Return pending messages addressed to this agent or broadcast, priority ASC."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, from_id, to_id, priority, content
                FROM messages
                WHERE (to_id = ? OR to_id = 'broadcast') AND status = 'pending'
                ORDER BY priority ASC, created_at ASC
                """,
                (agent_id,),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                conn.execute(
                    f"UPDATE messages SET status = 'delivered' WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )
        return json.dumps([dict(r) for r in rows])
    except Exception as e:
        logging.exception("read_messages failed")
        return f"error: {e}"


@mcp.tool()
def send_message(from_id: str, to_id: str, content: str, priority: int = 5) -> str:
    """Write a message onto the S-Bus."""
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO messages (from_id, to_id, priority, status, content)"
                " VALUES (?, ?, ?, 'pending', ?)",
                (from_id, to_id, priority, content),
            )
        return "ok"
    except Exception as e:
        logging.exception("send_message failed")
        return f"error: {e}"


@mcp.tool()
def update_status(agent_id: str, state: str, current_task: str = "") -> str:
    """Upsert agent state and heartbeat; increments context_turns each call."""
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_status
                    (agent_id, updated_at, state, current_task, context_turns, last_heartbeat)
                VALUES (?, CURRENT_TIMESTAMP, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id) DO UPDATE SET
                    updated_at     = CURRENT_TIMESTAMP,
                    state          = excluded.state,
                    current_task   = excluded.current_task,
                    context_turns  = agent_status.context_turns + 1,
                    last_heartbeat = CURRENT_TIMESTAMP
                """,
                (agent_id, state, current_task),
            )
        return "ok"
    except Exception as e:
        logging.exception("update_status failed")
        return f"error: {e}"


@mcp.tool()
def get_shared_state(key: str) -> str:
    """Read a key from shared_state; returns JSON null if not found."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT value FROM shared_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else "null"
    except Exception as e:
        logging.exception("get_shared_state failed")
        return f"error: {e}"


@mcp.tool()
def set_shared_state(key: str, value: str) -> str:
    """Write a JSON-serializable value to shared_state."""
    try:
        json.loads(value)
    except json.JSONDecodeError as e:
        return f"error: value must be valid JSON — {e}"
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO shared_state (key, updated_at, value)
                VALUES (?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP,
                    value      = excluded.value
                """,
                (key, value),
            )
        return "ok"
    except Exception as e:
        logging.exception("set_shared_state failed")
        return f"error: {e}"


@click.command()
@click.option(
    "--synapse-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def main(synapse_dir: Path) -> None:
    global _db_path
    _db_path = synapse_dir / "synapse.db"

    logging.basicConfig(
        filename=str(synapse_dir / "logs" / "mcp.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
