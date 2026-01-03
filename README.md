# linear-local-mcp

MCP server for fast, local-only access to Linear data via the Linear.app macOS cache.

## What it does

This MCP server reads Linear's local IndexedDB cache directly, providing instant access to your Linear data without API calls. Perfect for quickly browsing issues, searching, and getting context about your team's work.

**Performance**: Load ~24,000 issues in under 1 second vs. multiple API round-trips.

## Requirements

- **macOS** (Linear.app stores its cache at `~/Library/Application Support/Linear/`)
- **Python 3.10+**
- **Linear.app** installed and logged in (to populate the local cache)

## Installation

### Using uvx (recommended)

```bash
uvx linear-local-mcp
```

### Using pipx

```bash
pipx run linear-local-mcp
```

### From source

```bash
git clone --recursive https://github.com/gyfis/linear-local-mcp
cd linear-local-mcp
uv run linear-local-mcp
```

## Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "linear-local": {
      "command": "uvx",
      "args": ["linear-local-mcp"]
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `list_issues` | List issues with filters (assignee, team, state_type, priority, updated_after). Paginated. |
| `get_issue` | Get a single issue by identifier (e.g., `T-1234`) |
| `search_issues` | Search issues by title. Paginated. |
| `list_users` | List all users with issue counts |
| `get_user` | Get a user by name |
| `list_teams` | List all teams with issue counts |
| `list_states` | List workflow states |
| `get_my_issues` | Get issues for a user with counts by state type. Supports `updated_after` filter. Paginated. |
| `get_summary` | Get counts of teams, users, states, and issues |

### Filtering by Date

The `list_issues` and `get_my_issues` tools support an `updated_after` parameter to filter issues by last update time:

```
list_issues(updated_after="2024-01-01T00:00:00Z")
get_my_issues(name="me", updated_after="2024-12-25T00:00:00Z")
```

This accepts ISO-8601 datetime strings.

### Pagination

Tools that return large result sets (`list_issues`, `search_issues`, `get_my_issues`) support cursor-based pagination:

- Pass `limit` to control page size (default 50, max 100)
- Response includes `nextCursor` if there are more results
- Pass `cursor` parameter with the `nextCursor` value to get the next page

Example flow:
1. Call `list_issues(assignee="me", limit=20)` → returns first 20 issues + `nextCursor`
2. Call `list_issues(assignee="me", limit=20, cursor="abc123")` → returns next 20 issues

## Example Usage

Once configured, you can ask Claude:

- "What issues are assigned to me?"
- "Show me high priority bugs in the T team"
- "Search for issues about authentication"
- "Who has the most open issues?"

## Limitations

- **macOS only** - Reads the Linear.app local cache
- **Read-only** - Cannot create or update issues (use the official Linear MCP for that)
- **Data freshness** - Data is only as fresh as Linear.app's last sync
- **Cache TTL** - Data is cached for 5 minutes before reloading from disk

## How it works

Linear.app (an Electron app) stores a local cache of your Linear data in IndexedDB, which is backed by LevelDB on disk. This MCP server uses [ccl_chromium_reader](https://github.com/cclgroupltd/ccl_chromium_reader) to read Chrome/Electron's IndexedDB format directly.

The server auto-detects Linear's internal object store structure by sampling records, so it should continue working even if Linear updates their schema.

## Comparison with Official Linear MCP

| Feature | linear-local-mcp | Official Linear MCP |
|---------|------------------|---------------------|
| Speed | Instant (local) | Network latency |
| Read issues | Yes | Yes |
| Create/update issues | No | Yes |
| Requires API key | No | Yes |
| Works offline | Yes | No |
| Data freshness | Last Linear.app sync | Real-time |

Use this for fast reads; use the official Linear MCP when you need to make changes.

## License

MIT
