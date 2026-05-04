"""Functional tests for the synapse MCP server (all 5 tools)."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SERVER_CMD = [sys.executable, "-m", "synapse.mcp_server"]

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def synapse_dir(tmp_path: Path) -> Path:
    """Create a minimal .synapse dir with an initialised DB."""
    from synapse.db import init_db

    sd = tmp_path / ".synapse"
    (sd / "logs").mkdir(parents=True)
    (sd / "pids").mkdir()
    init_db(sd / "synapse.db")
    return sd


class MCPClient:
    """Thin wrapper around a synapse-mcp-server subprocess."""

    def __init__(self, synapse_dir: Path) -> None:
        self._proc = subprocess.Popen(
            SERVER_CMD + ["--synapse-dir", str(synapse_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._id = 1
        self._handshake()

    def _send(self, msg: dict) -> None:
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> dict:
        line = self._proc.stdout.readline()
        return json.loads(line)

    def _handshake(self) -> None:
        self._send(INITIALIZE)
        self._recv()  # initialize response
        self._send(INITIALIZED)  # notification — no response

    def call(self, tool: str, **kwargs) -> str:
        """Call a tool and return the text result."""
        self._id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": kwargs},
        })
        resp = self._recv()
        assert "error" not in resp, f"RPC error: {resp['error']}"
        content = resp["result"]["content"]
        return content[0]["text"]

    def close(self) -> None:
        self._proc.stdin.close()
        self._proc.wait(timeout=5)


@pytest.fixture()
def client(synapse_dir: Path):
    c = MCPClient(synapse_dir)
    yield c
    c.close()


def db_conn(synapse_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(synapse_dir / "synapse.db")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_update_status(client: MCPClient, synapse_dir: Path) -> None:
    result = client.call("update_status", agent_id="agent_a", state="idle", current_task="testing")
    assert result == "ok"

    with db_conn(synapse_dir) as conn:
        row = conn.execute("SELECT * FROM agent_status WHERE agent_id = 'agent_a'").fetchone()
    assert row["state"] == "idle"
    assert row["current_task"] == "testing"
    assert row["context_turns"] == 1
    assert row["last_heartbeat"] is not None


def test_update_status_increments_context_turns(client: MCPClient, synapse_dir: Path) -> None:
    client.call("update_status", agent_id="agent_a", state="working", current_task="step 1")
    client.call("update_status", agent_id="agent_a", state="working", current_task="step 2")
    client.call("update_status", agent_id="agent_a", state="idle", current_task="done")

    with db_conn(synapse_dir) as conn:
        row = conn.execute("SELECT context_turns FROM agent_status WHERE agent_id = 'agent_a'").fetchone()
    assert row["context_turns"] == 3


def test_send_and_read_messages(client: MCPClient, synapse_dir: Path) -> None:
    client.call("send_message", from_id="human", to_id="agent_a", content="hello", priority=0)

    result = client.call("read_messages", agent_id="agent_a")
    messages = json.loads(result)

    assert len(messages) == 1
    assert messages[0]["from_id"] == "human"
    assert messages[0]["to_id"] == "agent_a"
    assert messages[0]["priority"] == 0
    assert messages[0]["content"] == "hello"


def test_read_messages_marks_delivered(client: MCPClient, synapse_dir: Path) -> None:
    client.call("send_message", from_id="human", to_id="agent_a", content="msg1")
    client.call("read_messages", agent_id="agent_a")

    with db_conn(synapse_dir) as conn:
        rows = conn.execute("SELECT status FROM messages").fetchall()
    assert all(r["status"] == "delivered" for r in rows)


def test_read_messages_returns_empty_when_none(client: MCPClient) -> None:
    result = client.call("read_messages", agent_id="agent_a")
    assert json.loads(result) == []


def test_read_messages_includes_broadcast(client: MCPClient) -> None:
    client.call("send_message", from_id="agent_b", to_id="broadcast", content="hey all", priority=5)

    result = client.call("read_messages", agent_id="agent_a")
    messages = json.loads(result)
    assert len(messages) == 1
    assert messages[0]["to_id"] == "broadcast"


def test_read_messages_priority_order(client: MCPClient) -> None:
    client.call("send_message", from_id="human", to_id="agent_a", content="low", priority=10)
    client.call("send_message", from_id="human", to_id="agent_a", content="urgent", priority=0)
    client.call("send_message", from_id="human", to_id="agent_a", content="normal", priority=5)

    messages = json.loads(client.call("read_messages", agent_id="agent_a"))
    priorities = [m["priority"] for m in messages]
    assert priorities == sorted(priorities)


def test_set_and_get_shared_state(client: MCPClient) -> None:
    client.call("set_shared_state", key="task:current", value='"write tests"')
    result = client.call("get_shared_state", key="task:current")
    assert result == '"write tests"'


def test_get_shared_state_missing_key(client: MCPClient) -> None:
    result = client.call("get_shared_state", key="nonexistent")
    assert result == "null"


def test_set_shared_state_rejects_invalid_json(client: MCPClient) -> None:
    result = client.call("set_shared_state", key="bad", value="not json {")
    assert result.startswith("error:")


def test_set_shared_state_overwrites(client: MCPClient, synapse_dir: Path) -> None:
    client.call("set_shared_state", key="k", value='"first"')
    client.call("set_shared_state", key="k", value='"second"')

    with db_conn(synapse_dir) as conn:
        row = conn.execute("SELECT value FROM shared_state WHERE key = 'k'").fetchone()
    assert row["value"] == '"second"'
