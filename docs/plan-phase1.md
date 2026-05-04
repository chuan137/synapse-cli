# SYNAPSE — Phase 1: Foundation
**Implementation Plan · v1.0**
Scope: CLI scaffolding · S-Bus schema · MCP server · S-Deck skeleton

---

## Overview

Phase 1 establishes the foundation that all future Synapse capabilities will build on. The goal is a working end-to-end skeleton: you can run `synapse init` in any project directory, get a running database, a registered MCP server, and a live web panel — all scoped to that project.

> **Phase 1 Outcome:** A Claude agent connected to a Synapse instance can read messages, update its status, and write to shared state — entirely through MCP tools. You can observe all of this in real time from S-Deck.

---

## Architecture Snapshot

The Phase 1 system has three runtime components:

| Component | Process | Responsibility |
|---|---|---|
| `synapse.db` | SQLite (embedded) | All persistent state: messages, agent status, tool metrics, shared KV store |
| `mcp_server.py` | stdio process (per agent) | Exposes S-Bus as MCP tools; each agent gets its own process instance |
| `deck.py` | uvicorn HTTP server | FastAPI + HTMX web panel for human observation and P0 command injection |

---

## Milestones

### M1 · CLI Scaffold

The `synapse` command is installed globally via `uv` and supports the core lifecycle verbs.

| # | Deliverable | Output | Status |
|---|---|---|---|
| 1.1 | Project directory structure (`setup.py`, package layout) | `~/synapse-cli/` installable package | DONE |
| 1.2 | `synapse init` — creates `.synapse/` in current directory | `.synapse/synapse.db`, `config.json`, `logs/`, `pids/` | DONE |
| 1.3 | `synapse start` — launches S-Deck | Background uvicorn process, PID recorded | DONE |
| 1.4 | `synapse stop` — graceful shutdown | Processes terminated, agents marked offline | DONE |
| 1.5 | `synapse status` — prints runtime state | S-Deck state + agent table with heartbeat age | DONE |
| 1.6 | `synapse destroy` — teardown | Stops services, removes `.synapse/`, unregisters MCP | DONE |

---

### M2 · S-Bus Database

SQLite schema that serves as the shared memory and message bus for all agents.

| # | Deliverable | Output | Status |
|---|---|---|---|
| 2.1 | `messages` table | Priority inbox for human→agent and agent→agent comms | DONE |
| 2.2 | `agent_status` table | Heartbeat, state, workflow, context turn count | DONE |
| 2.3 | `tool_metrics` table | Per-call latency and error tracking for observability | DONE |
| 2.4 | `shared_state` table | JSON key-value store for cross-agent shared context | DONE |
| 2.5 | Schema migration script | Idempotent `CREATE TABLE IF NOT EXISTS` via `db.py` | DONE |

---

### M3 · MCP Server (S-Bus)

A stdio MCP server that exposes the S-Bus database as agent-callable tools. Registered per-project via `claude mcp add --scope project`.

| # | Deliverable | Output | Status |
|---|---|---|---|
| 3.1 | `read_messages` tool | Returns pending messages for calling agent, ordered by priority | DONE |
| 3.2 | `send_message` tool | Writes a message to the bus with priority and routing | DONE |
| 3.3 | `update_status` tool | Agent updates its own state, heartbeat, current task | DONE |
| 3.4 | `get_shared_state` / `set_shared_state` tools | Read and write the shared KV store | DONE |
| 3.5 | `claude mcp add` registration in `synapse init` | Project-scoped MCP entry in `.mcp.json` | DONE |

---

### M4 · S-Deck Web Panel

A minimal FastAPI + HTMX dashboard. No JavaScript framework — server-side rendering only in Phase 1.

| # | Deliverable | Output | Status |
|---|---|---|---|
| 4.1 | FastAPI app skeleton with uvicorn | HTTP server starts on configurable port | DONE (stub) |
| 4.2 | Agent status panel (auto-refresh every 5s) | Shows state, current task, last heartbeat, context turns | Phase 2 |
| 4.3 | Message log view | Last 50 messages, filterable by agent and priority | Phase 2 |
| 4.4 | P0 command input box | Write a message to the bus with priority=0 | Phase 2 |
| 4.5 | Basic health indicators | Red/amber/green per agent based on heartbeat age | Phase 2 |

---

## File Structure After Phase 1

```
~/synapse-cli/                 # CLI source (install once)
├── synapse/
│   ├── cli.py                 # synapse init/start/stop/status
│   ├── db.py                  # Schema init, migration helpers
│   ├── mcp_server.py          # S-Bus MCP server (stdio)
│   └── deck.py                # S-Deck FastAPI + HTMX
└── setup.py

~/your-project/                # Any project using Synapse
├── .synapse/                  # Created by synapse init
│   ├── synapse.db             # The S-Bus database
│   ├── config.json            # Port, agent IDs, workflow config
│   ├── logs/
│   └── pids/                  # deck.pid, mcp.pid
└── .claude/                   # Created by claude mcp add
    └── claude_desktop_config.json
```

---

## Execution Sequence

Build in this order to ensure each layer is testable before adding the next:

1. `setup.py` — make the package installable with `uv pip install -e .`
2. `db.py` — write and test `schema.sql`; verify tables with `sqlite3` CLI
3. `cli.py` (init only) — test that `.synapse/` and `config.json` are created correctly
4. `mcp_server.py` — implement all four tools; test with `claude mcp add` locally
5. `cli.py` (start/stop/status) — wire up process management for mcp_server and deck
6. `deck.py` — build panel page by page; test each HTMX endpoint independently
7. End-to-end test — agent reads a message you wrote from S-Deck

---

## Out of Scope for Phase 1

- tmux idle detection and async P0 injection (Phase 2)
- Architect / Developer agent system prompts and behavioral hooks (Phase 2)
- Cognitive restart and RESET command protocol (Phase 2)
- Risk alerting, context overload detection (Phase 3)
- Task tree visualization (Phase 3)

---

*Phase 1 complete when: agent reads a P0 message sent from S-Deck, entirely through MCP.*
