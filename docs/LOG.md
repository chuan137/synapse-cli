# Synapse CLI — Development Log

---

## 2026-05-04 — Bootstrap: `init` command + template rendering

### What was built

**`synapse/db.py`**
- Implemented `init_db(path: Path)` using stdlib `sqlite3`
- Creates all four schema tables on first run (idempotent via `CREATE TABLE IF NOT EXISTS`):
  - `messages` — S-Bus message queue (priority, status, from/to agent IDs)
  - `agent_status` — per-agent heartbeat and state tracking
  - `tool_metrics` — tool call observability (duration, status, errors)
  - `shared_state` — key-value store for cross-agent context (JSON values)

**`synapse/templates/__init__.py`**
- Empty file added to make `synapse/templates/` a proper subpackage
- Required for `importlib.resources.files("synapse.templates")` to resolve correctly at runtime

**`synapse/cli.py`**
- Click group `cli` (entry point: `synapse`)
- `init` command:
  - Creates `.synapse/logs/` and `.synapse/pids/` directories
  - Calls `init_db()` to initialise `synapse.db`
  - Writes `config.json` (port, agent_ids, workflow, agent_roles_description)
  - Loads `CLAUDE.project.md` from the bundled package via `importlib.resources.files()` (not `pkg_resources`)
  - Renders it with Jinja2 — `{{AGENT_ROLES}}` is replaced by the `--roles` option value
  - Writes the rendered output to `CLAUDE.md` in the project root
  - Registers the MCP server via `claude mcp add synapse-bus --scope project synapse-mcp-server --synapse-dir <abs>`
- `start`, `stop`, `status`, `destroy` — stubs with `require_synapse_root()` guard (exit 1 if no `.synapse/` found)
- `find_synapse_root()` — walks up from CWD to locate `.synapse/`, same pattern as `git`

**`pyproject.toml`**
- Added `[project.scripts]`:
  - `synapse` → `synapse.cli:cli`
  - `synapse-mcp-server` → `synapse.mcp_server:main` (used by `claude mcp add` at init time)

### Design decisions

| Decision | Rationale |
|---|---|
| `importlib.resources` over `pkg_resources` | stdlib in 3.11+, no `setuptools` runtime dep |
| Jinja2 over `str.replace()` | Already a dep; handles curly braces in user-supplied role text safely |
| `synapse-mcp-server --synapse-dir` pattern | Pins each MCP registration to its project's `.synapse/` at init time; no CWD ambiguity when agents invoke it |
| Stubs raise `NotImplementedError` | Explicit failure is better than silent no-ops; guards are in place |

---

## 2026-05-04 — MCP server, CLI commands, tests, and extra prompts

### What was built

**`synapse/mcp_server.py`**
- FastMCP stdio server exposing 5 tools backed by SQLite (`sqlite3` sync, runs in FastMCP thread pool):
  - `read_messages(agent_id)` — fetches pending messages for an agent plus broadcast, marks them `delivered`, returns priority-ordered JSON
  - `send_message(from_id, to_id, content, priority=5)` — inserts a message onto the bus
  - `update_status(agent_id, state, current_task)` — upserts agent row, increments `context_turns`, refreshes `last_heartbeat`
  - `get_shared_state(key)` — returns stored JSON value or `"null"` if absent
  - `set_shared_state(key, value)` — validates JSON then upserts into `shared_state`
- All tools catch exceptions and return `"error: ..."` strings rather than raising
- Logs to `.synapse/logs/mcp.log`; never writes to stdout (reserved for MCP protocol)
- Entry point: `synapse-mcp-server --synapse-dir <path>`

**`synapse/cli.py`** — full implementations replacing stubs:
- `start` — spawns uvicorn (`synapse.deck:app`) as a background process via `subprocess.Popen`; passes `SYNAPSE_DIR` env var; writes PID to `pids/deck.pid`; guards against double-start
- `stop` — SIGTERMs all `*.pid` files, removes them, marks all agents `offline` in DB; reports stale PIDs gracefully
- `status` — prints S-Deck state (running/stopped/dead) and an agent table with state, context turns, heartbeat age, and current task
- `destroy --yes` — stops services, calls `claude mcp remove synapse-bus --scope project`, removes `.synapse/` with `shutil.rmtree`
- Added `--extra` option to `init`: extra instructions are rendered into a **Project-Specific Instructions** section in `CLAUDE.md` via a Jinja2 `{% if %}` block; stored in `config.json` as `extra_instructions`

**`synapse/deck.py`**
- Minimal FastAPI stub with `/health` route; sufficient for `start`/`stop` to work; full S-Deck dashboard deferred to Phase 2

**`synapse/templates/CLAUDE.project.md`**
- Added `{% if EXTRA_INSTRUCTIONS %}` block rendering a **Project-Specific Instructions** section after the escalation section; absent when `--extra` is not supplied

### Bug fixes

| Bug | Fix |
|---|---|
| `claude mcp add` parsed `--synapse-dir` as its own flag | Added `--` separator before `synapse-mcp-server` in the subprocess call |
| `python -m synapse.mcp_server` silently exited | Added `if __name__ == "__main__": main()` guard — Click entry points are not invoked on module import |

### Tests — 42 passing

| File | Count | Scope |
|---|---|---|
| `tests/test_mcp_server.py` | 11 | All 5 MCP tools via stdio subprocess + DB state assertions |
| `tests/test_cli.py` | 21 | All 5 CLI commands via `CliRunner`; mocks for subprocess/os.kill; edge cases |
| `tests/test_prompts.py` | 10 | `--extra` rendering, visibility to both agents, ordering, config persistence, project isolation |

### Design decisions

| Decision | Rationale |
|---|---|
| `sqlite3` sync in MCP tools | FastMCP runs sync tools in a thread pool; no async overhead needed for single-file SQLite |
| `sys.executable -m uvicorn` in `start` | Ensures uvicorn from the active venv is used regardless of `PATH` |
| `{% if EXTRA_INSTRUCTIONS %}` Jinja2 block | Keeps the section entirely absent from `CLAUDE.md` when no extra text is supplied, avoiding empty headings |
| `--yes` flag on `destroy` | Prevents accidental removal; explicit opt-in required for destructive operations |
