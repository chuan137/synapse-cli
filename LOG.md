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
