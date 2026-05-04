# CLAUDE.md — Synapse CLI Development

You are working on **Synapse**, a multi-agent governance system. This file describes the codebase you are developing and the conventions you must follow.

---

## What Synapse Is

Synapse is an upper-layer governance tool for multi-agent AI workflows. It is **not** a workflow engine — it sits above existing workflows (e.g. Manila cherry-pick) and provides:

- A shared message bus (S-Bus) backed by SQLite
- A per-project MCP server that agents connect to via stdio
- A web dashboard (S-Deck) for human observation and P0 command injection
- A CLI (`synapse`) for lifecycle management: init, start, stop, status

Synapse is **multi-instance**: each project gets its own `.synapse/` directory, database, and MCP registration — analogous to `git init`.

---

## Repository Layout

```
~/synapse-cli/
├── synapse/
│   ├── __init__.py
│   ├── cli.py           # Click CLI: init, start, stop, status, destroy
│   ├── db.py            # Schema creation, migration, query helpers
│   ├── mcp_server.py    # stdio MCP server — the S-Bus agent interface
│   └── deck.py          # FastAPI + HTMX web dashboard (S-Deck)
├── setup.py
└── CLAUDE.md            # This file
```

When a user runs `synapse init` in their project, the following is created:

```
their-project/
├── .synapse/
│   ├── synapse.db       # SQLite database — single source of truth
│   ├── config.json      # Instance config: port, agent_ids, workflow
│   ├── logs/
│   └── pids/            # deck.pid, mcp.pid
└── .claude/
    └── claude_desktop_config.json  # MCP registration (--scope project)
```

---

## Database Schema

Four tables. Never modify schema without updating `db.py` and `bus/schema.sql`.

```sql
-- Message bus
messages (id, created_at, from_id, to_id, priority, status, content)
-- priority: 0=P0 urgent, 5=normal, 10=low
-- status: pending | delivered | acked
-- from_id / to_id: 'human' | 'agent_a' | 'agent_b' | 'broadcast'

-- Agent heartbeat and state
agent_status (agent_id, updated_at, state, current_task, workflow, context_turns, last_heartbeat)
-- state: offline | idle | working | blocked | error

-- Tool call observability
tool_metrics (id, recorded_at, agent_id, tool_name, duration_ms, status, error_msg)

-- Shared key-value store (JSON values)
shared_state (key, updated_at, value)
```

---

## MCP Tools (mcp_server.py)

The MCP server exposes exactly these tools. Do not add tools without updating this list and the corresponding deck.py display logic.

| Tool | Description |
|---|---|
| `read_messages` | Returns pending messages for the calling agent, ordered by priority ASC |
| `send_message` | Writes a message to the bus; args: to_id, content, priority (default 5) |
| `update_status` | Agent updates its own state, current_task, increments context_turns |
| `get_shared_state` | Read a key from shared_state; returns null if not found |
| `set_shared_state` | Write a JSON-serializable value to a key in shared_state |

The MCP server is registered per-project using:
```bash
claude mcp add synapse-bus \
  --scope project \
  python /absolute/path/to/.synapse/mcp_server.py
```

This is called automatically inside `synapse init`.

---

## CLI Commands (cli.py)

All commands must be run from within a project directory (or a subdirectory). They locate the `.synapse/` instance by walking up the directory tree — same pattern as `git`.

| Command | Behaviour |
|---|---|
| `synapse init` | Creates `.synapse/`, initialises DB, registers MCP, writes `config.json` |
| `synapse start` | Starts `mcp_server.py` (stdio, managed) and `deck.py` (uvicorn background) |
| `synapse stop` | Sends SIGTERM to PIDs in `pids/`, updates agent states to `offline` |
| `synapse status` | Reads `agent_status` and `pids/`; prints a summary table |
| `synapse destroy` | Stops services, removes `.synapse/`, unregisters MCP |

---

## S-Deck (deck.py)

FastAPI + HTMX. Server-side rendering only — no JS framework. Key routes:

| Route | Description |
|---|---|
| `GET /` | Main dashboard: agent status cards + message log |
| `GET /status` | HTMX partial: agent status cards (auto-polled every 5s) |
| `GET /messages` | HTMX partial: last 50 messages |
| `POST /command` | Write a P0 message (priority=0) to the bus from the human |

Health indicator logic: green if `last_heartbeat` < 30s ago, amber < 120s, red otherwise.

---

## Development Conventions

- **Python version**: 3.11+
- **Package manager**: `uv` — always use `uv add` / `uv pip install`, never bare `pip`
- **No global state**: the `.synapse/` path is resolved at runtime from CWD; never hardcode paths
- **DB access**: always use `aiosqlite` for async routes in deck.py; use `sqlite3` (sync) in cli.py and mcp_server.py
- **Error handling**: MCP tool errors must return a structured error string, never raise unhandled exceptions
- **Logging**: write to `.synapse/logs/deck.log` and `.synapse/logs/mcp.log` — never to stdout in background processes

---

## What Not To Touch

- Do not modify `.claude/claude_desktop_config.json` manually — it is managed by `claude mcp add`
- Do not add workflow-specific logic to Synapse core — workflows belong in the user's project
- Do not add inter-agent communication logic beyond message routing — Synapse routes, agents decide
