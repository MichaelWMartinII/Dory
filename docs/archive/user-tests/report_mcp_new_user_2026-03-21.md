# MCP New-User Test Report
**Date:** 2026-03-21
**Version tested:** dory-memory 0.3.3 (bugs found), fixed in 0.3.4
**Environment:** macOS Darwin 24.6.0, Python 3.14, clean venv at `/tmp/dory_mcp_test`
**Tester:** Claude Code (simulated new-user walkthrough via subagent)

---

## Method

Installed `dory-memory[mcp]` from PyPI into a clean venv, then followed the README
MCP setup instructions exactly as a new user would. Verified MCP protocol handshake,
tool availability, and Claude Code integration.

```bash
python3 -m venv /tmp/dory_mcp_test
source /tmp/dory_mcp_test/bin/activate
pip install "dory-memory[mcp]"
```

Installed packages: `dory-memory 0.3.3`, `mcp 1.26.0`, plus transitive dependencies
(anyio, httpx, pydantic, starlette, uvicorn, pyjwt, etc.)

---

## Step 1 — Entry Point Verification

**Test:**
```bash
which dory-mcp
dory-mcp --help
```

**Result: PASS**

`dory-mcp` installed at `/tmp/dory_mcp_test/bin/dory-mcp`.

Help output:
```
usage: dory-mcp [-h] [--db DB]

Dory MCP server — graph memory for AI agents

options:
  -h, --help  show this help message and exit
  --db DB     Path to Dory database file. Overrides DORY_DB_PATH env var.
```

**Minor observation:** `DORY_DB_PATH` is mentioned in `--help` but not documented in the README.

---

## Step 2 — MCP Server Startup & Handshake

**Test:** Sent a JSON-RPC `initialize` message via subprocess and checked the response.

```python
import subprocess, json
proc = subprocess.Popen(
    ['/tmp/dory_mcp_test/bin/dory-mcp', '--db', '/tmp/dory_mcp_test.db'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
init_msg = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"}
    }
}) + '\n'
stdout, stderr = proc.communicate(input=init_msg.encode(), timeout=10)
```

**Result: PASS**

Server started and responded within 1s. Response included:
```json
{
  "protocolVersion": "2024-11-05",
  "capabilities": {"tools": {"listChanged": false}},
  "serverInfo": {"name": "Dory Memory", "version": "1.26.0"},
  "instructions": "Dory is a persistent memory graph for AI agents. ..."
}
```

**Bug found:** `serverInfo.version` reported `1.26.0` — the MCP library version, not
`0.3.3` (the dory-memory version). A user verifying their install version via the MCP
handshake gets a wrong answer.

**Fix applied in 0.3.4:** Added `importlib.metadata.version("dory-memory")` lookup to
set the correct version in `FastMCP()`.

---

## Step 3 — Tool Availability

**Test:** Sent `tools/list` request and verified all 5 documented tools were present.

**Result: PASS** — All 5 tools returned with correct names and parameters:

| Tool | Parameters | Status |
|---|---|---|
| `dory_query` | `topic: str` (required) | ✓ |
| `dory_observe` | `content: str` (required), `node_type: str` (default: "CONCEPT") | ✓ |
| `dory_consolidate` | none | ✓ |
| `dory_visualize` | `include_archived: bool` (default: false) | ✓ |
| `dory_stats` | none | ✓ |

---

## Step 4 — Functional Tool Tests

Tested each tool via actual MCP tool call messages:

| Tool Call | Result | Output |
|---|---|---|
| `dory_observe("Test user prefers local-first AI", "PREFERENCE")` | ✓ PASS | `Stored [PREFERENCE]: Test user prefers local-first AI (id: f92f8b64)` |
| `dory_stats` | ✓ PASS | `Nodes: 1  Edges: 0  Core: 0` |
| `dory_query("local AI preference")` | ✓ PASS | `Activated memories:\n- [PREFERENCE] Test user prefers local-first AI` |
| `dory_consolidate` | ✓ PASS | Full consolidation report, `Promoted core: 1` |
| `dory_visualize` | ✓ PASS | Generated HTML file, opened in browser |
| `dory_observe` with invalid `node_type` | ✓ PASS | Human-readable error listing valid types |

---

## Step 5 — Default DB Path Bug

**Test:** Ran `dory-mcp` without `--db` and checked where the database was created.

**Result: CRITICAL BUG**

Without `--db`, the DB was created at:
```
/tmp/dory_mcp_test/lib/python3.14/site-packages/engram.db
```

This is inside the Python package installation directory. The `DEFAULT_GRAPH_PATH` was
defined as `Path(__file__).parent.parent / "engram.db"` — two levels up from
`dory/store.py`, landing in `site-packages/`.

**Impact:**
- Memory is written to a location that gets wiped on `pip install --upgrade dory-memory`
- Every new user who doesn't read the `--db` docs loses their memory on upgrade
- The README's first `claude mcp add` example (no `--db`) silently uses this bad path

**Fix applied in 0.3.4:**
```python
DEFAULT_GRAPH_PATH = Path.home() / ".dory" / "engram.db"
```
`~/.dory/` is created automatically on first use (existing `path.parent.mkdir(parents=True, exist_ok=True)` in `store.py` already handles this).

---

## Step 6 — Claude Code Integration (PATH Issue)

**Test:** Followed README instruction exactly:
```bash
pip install 'dory-memory[mcp]'
claude mcp add --scope user dory -- dory-mcp
```

**Result: WOULD FAIL for most users**

This command works only if `dory-mcp` is on the system PATH that Claude Code inherits
at startup. On Python 3.12+ (where venv is mandatory) and any venv install, the binary
lives at `/path/to/venv/bin/dory-mcp` — not on the system PATH.

Claude Code would register the server but fail to start it silently. `claude mcp list`
would show the server as disconnected or errored.

**How the real Dory MCP is configured on Michael's machine** (from `~/.claude.json`):
```json
{
  "dory": {
    "type": "stdio",
    "command": "/Users/michael/Repo/Dory/.venv/bin/python",
    "args": ["/Users/michael/Repo/Dory/dory_mcp.py", "--db", "/Users/michael/Repo/Dory/engram.db"]
  }
}
```
This uses the full path — which is why it works. The README didn't document this requirement.

**Fix applied in 0.3.4:** README updated to:
```bash
pip install 'dory-memory[mcp]'
which dory-mcp   # find the full path
claude mcp add --scope user dory -- /full/path/to/dory-mcp --db ~/.dory/engram.db
```

---

## Step 7 — README Accuracy Review (MCP Section)

| Claim | Accurate? | Notes |
|---|---|---|
| `pip install 'dory-memory[mcp]'` works | ✓ | |
| `claude mcp add --scope user dory -- dory-mcp` works | ✗ | PATH issue for venv users |
| 5 tools exposed with correct names | ✓ | |
| `--db` flag works | ✓ | |
| No mention of `which dory-mcp` | ✗ | Critical missing step |
| No mention of `claude mcp list` to verify | ✗ | Missing verification step |
| No `DORY_DB_PATH` documentation | ✗ | Documented in --help but not README |
| No Claude Desktop config | ✗ | Only in dory_mcp.py docstring |

---

## Issues Found

| Severity | Issue | Status |
|---|---|---|
| Critical | Default DB path resolves to `site-packages/engram.db` — wiped on upgrade | Fixed in 0.3.4 |
| Critical | `claude mcp add -- dory-mcp` fails for venv users (PATH not inherited) | Fixed in 0.3.4 (README) |
| Medium | MCP handshake reports MCP lib version (`1.26.0`) not dory version | Fixed in 0.3.4 |
| Medium | `DORY_DB_PATH` env var not documented in README | Fixed in 0.3.4 (README) |
| Medium | No Claude Desktop config in README | Fixed in 0.3.4 (README) |
| Minor | No `claude mcp list` verification step after registration | Fixed in 0.3.4 (README) |
| Minor | No restart instruction after `claude mcp add` | Not yet addressed |

---

## What Worked Well

- Install clean, all MCP dependencies resolved
- Server starts and responds to JSON-RPC within 1s
- All 5 tools present with correct signatures
- All tool calls return correct output
- Error handling on invalid inputs is good (human-readable, not exceptions)
- Consolidation, query, and observe all functionally correct

---

## Recommendations Applied (0.3.4)

1. ✅ Fixed `DEFAULT_GRAPH_PATH` → `~/.dory/engram.db`
2. ✅ README: added `which dory-mcp` step
3. ✅ README: canonical form uses full path + `--db ~/.dory/engram.db`
4. ✅ README: added `claude mcp list` verification step
5. ✅ README: documented `DORY_DB_PATH` env var
6. ✅ README: added Claude Desktop JSON config block
7. ✅ `mcp_server.py`: reports correct dory-memory version in handshake

## Remaining Open Items

- No "restart Claude Code" instruction after `claude mcp add` (minor UX gap)
- Claude Desktop setup not tested end-to-end (config documented but not verified)
