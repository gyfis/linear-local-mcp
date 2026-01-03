"""
MCP Server for Linear Local Data.

Provides fast, local-only access to Linear data through the MCP protocol.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .reader import LinearLocalReader

mcp = FastMCP(
    "Linear Local",
    instructions=(
        "This server provides fast, read-only access to Linear data from the local "
        "Linear.app cache on macOS. Data is only as fresh as Linear.app's last sync. "
        "Use this for quickly browsing issues, users, and teams without API latency."
    ),
)

# Lazy-loaded reader instance
_reader: LinearLocalReader | None = None


def get_reader() -> LinearLocalReader:
    """Get or create the LinearLocalReader instance."""
    global _reader
    if _reader is None:
        _reader = LinearLocalReader()
    return _reader


def _parse_datetime(dt_value: Any) -> float | None:
    """Parse a datetime value to Unix timestamp."""
    if dt_value is None:
        return None
    if isinstance(dt_value, (int, float)):
        # Already a timestamp (possibly in milliseconds)
        if dt_value > 1e12:  # Likely milliseconds
            return dt_value / 1000
        return dt_value
    if isinstance(dt_value, str):
        # ISO format string
        from datetime import datetime

        try:
            # Handle ISO format with or without timezone
            dt_str = dt_value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(dt_str)
            return dt.timestamp()
        except ValueError:
            return None
    return None


@mcp.tool()
def list_issues(
    assignee: str | None = None,
    team: str | None = None,
    state_type: str | None = None,
    priority: int | None = None,
    updated_after: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    List issues with optional filters and pagination.

    Args:
        assignee: Filter by assignee name (partial match)
        team: Filter by team key or name
        state_type: Filter by state type (started, unstarted, completed, canceled, backlog)
        priority: Filter by priority (1=Urgent, 2=High, 3=Normal, 4=Low)
        updated_after: Filter to issues updated after this ISO-8601 datetime (e.g., '2024-01-01T00:00:00Z')
        limit: Maximum number of issues to return per page (default 50, max 100)
        cursor: Pagination cursor from previous response (issue ID to start after)

    Returns:
        Dictionary with issues array, nextCursor (if more results), and totalCount
    """
    reader = get_reader()
    limit = min(limit, 100)  # Cap at 100

    # Parse updated_after filter
    updated_after_ts = None
    if updated_after:
        updated_after_ts = _parse_datetime(updated_after)
        if updated_after_ts is None:
            return {
                "error": f"Invalid updated_after format: {updated_after}",
                "issues": [],
                "nextCursor": None,
                "totalCount": 0,
            }

    # Resolve assignee ID if provided
    assignee_id = None
    if assignee:
        user = reader.find_user(assignee)
        if user:
            assignee_id = user["id"]
        else:
            return {"issues": [], "nextCursor": None, "totalCount": 0}

    # Resolve team ID if provided
    team_id = None
    if team:
        team_obj = reader.find_team(team)
        if team_obj:
            team_id = team_obj["id"]
        else:
            return {"issues": [], "nextCursor": None, "totalCount": 0}

    # Get all issues sorted by priority then ID for stable, meaningful pagination
    all_issues = sorted(
        reader.issues.values(), key=lambda x: (x.get("priority") or 4, x.get("id", ""))
    )

    # Filter issues
    filtered = []
    for issue in all_issues:
        if assignee_id and issue.get("assigneeId") != assignee_id:
            continue
        if team_id and issue.get("teamId") != team_id:
            continue
        if state_type:
            issue_state_type = reader.get_state_type(issue.get("stateId", ""))
            if issue_state_type != state_type:
                continue
        if priority is not None and issue.get("priority") != priority:
            continue
        if updated_after_ts is not None:
            issue_updated = _parse_datetime(issue.get("updatedAt"))
            if issue_updated is None or issue_updated < updated_after_ts:
                continue
        filtered.append(issue)

    total_count = len(filtered)

    # Apply cursor (skip issues until we pass the cursor ID)
    if cursor:
        skip = True
        filtered_after_cursor = []
        for issue in filtered:
            if skip:
                if issue.get("id") == cursor:
                    skip = False
                continue
            filtered_after_cursor.append(issue)
        filtered = filtered_after_cursor

    # Take limit + 1 to check if there are more
    page = filtered[: limit + 1]
    has_more = len(page) > limit
    page = page[:limit]

    # Enrich issues with state info
    results = []
    for issue in page:
        enriched = {
            **issue,
            "state": reader.get_state_name(issue.get("stateId", "")),
            "stateType": reader.get_state_type(issue.get("stateId", "")),
        }
        results.append(enriched)

    next_cursor = results[-1]["id"] if has_more and results else None

    return {
        "issues": results,
        "nextCursor": next_cursor,
        "totalCount": total_count,
    }


@mcp.tool()
def get_issue(identifier: str) -> dict[str, Any] | None:
    """
    Get a single issue by its identifier.

    Args:
        identifier: Issue identifier like 'T-1234' or 'EMA-567'

    Returns:
        The issue if found, None otherwise
    """
    reader = get_reader()
    issue = reader.get_issue_by_identifier(identifier)

    if issue:
        return {
            **issue,
            "state": reader.get_state_name(issue.get("stateId", "")),
            "stateType": reader.get_state_type(issue.get("stateId", "")),
        }
    return None


@mcp.tool()
def search_issues(
    query: str,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Search issues by title with pagination.

    Args:
        query: Search query (case-insensitive, matches anywhere in title)
        limit: Maximum number of results per page (default 50, max 100)
        cursor: Pagination cursor from previous response (issue ID to start after)

    Returns:
        Dictionary with issues array, nextCursor (if more results), and matchCount
    """
    reader = get_reader()
    limit = min(limit, 100)
    query_lower = query.lower()

    # Get all issues sorted by priority then ID for stable, meaningful pagination
    all_issues = sorted(
        reader.issues.values(), key=lambda x: (x.get("priority") or 4, x.get("id", ""))
    )

    # Filter by query
    filtered = []
    for issue in all_issues:
        title = issue.get("title", "") or ""
        if isinstance(title, bytes):
            title = title.decode("utf-8", errors="replace")
        if query_lower in title.lower():
            filtered.append(issue)

    match_count = len(filtered)

    # Apply cursor
    if cursor:
        skip = True
        filtered_after_cursor = []
        for issue in filtered:
            if skip:
                if issue.get("id") == cursor:
                    skip = False
                continue
            filtered_after_cursor.append(issue)
        filtered = filtered_after_cursor

    # Take limit + 1 to check if there are more
    page = filtered[: limit + 1]
    has_more = len(page) > limit
    page = page[:limit]

    results = [
        {
            **issue,
            "state": reader.get_state_name(issue.get("stateId", "")),
            "stateType": reader.get_state_type(issue.get("stateId", "")),
        }
        for issue in page
    ]

    next_cursor = results[-1]["id"] if has_more and results else None

    return {
        "issues": results,
        "nextCursor": next_cursor,
        "matchCount": match_count,
    }


@mcp.tool()
def list_users(limit: int = 100) -> list[dict[str, Any]]:
    """
    List all users.

    Args:
        limit: Maximum number of users to return (default 100)

    Returns:
        List of users with their issue counts
    """
    reader = get_reader()
    results = []

    for user in reader.users.values():
        issue_count = sum(
            1 for i in reader.issues.values() if i.get("assigneeId") == user["id"]
        )
        results.append({**user, "issueCount": issue_count})

        if len(results) >= limit:
            break

    # Sort by issue count descending
    results.sort(key=lambda x: -x.get("issueCount", 0))
    return results


@mcp.tool()
def get_user(name: str) -> dict[str, Any] | None:
    """
    Get a user by name.

    Args:
        name: User name to search for (partial match, prefers word-start matches)

    Returns:
        The user if found, None otherwise
    """
    reader = get_reader()
    user = reader.find_user(name)

    if user:
        issue_count = sum(
            1 for i in reader.issues.values() if i.get("assigneeId") == user["id"]
        )
        return {**user, "issueCount": issue_count}
    return None


@mcp.tool()
def list_teams() -> list[dict[str, Any]]:
    """
    List all teams.

    Returns:
        List of teams with their issue counts
    """
    reader = get_reader()
    results = []

    for team in reader.teams.values():
        issue_count = sum(
            1 for i in reader.issues.values() if i.get("teamId") == team["id"]
        )
        results.append({**team, "issueCount": issue_count})

    # Sort by key
    results.sort(key=lambda x: x.get("key", ""))
    return results


@mcp.tool()
def list_states(team: str | None = None) -> list[dict[str, Any]]:
    """
    List workflow states.

    Args:
        team: Optional team key or name to filter states

    Returns:
        List of workflow states
    """
    reader = get_reader()

    # Group states by type for better organization
    states_by_type: dict[str, list[dict[str, Any]]] = {}
    for state in reader.states.values():
        state_type = state.get("type", "unknown")
        if state_type not in states_by_type:
            states_by_type[state_type] = []
        states_by_type[state_type].append(state)

    # Flatten with type order
    type_order = ["backlog", "unstarted", "started", "completed", "canceled"]
    results = []
    for state_type in type_order:
        if state_type in states_by_type:
            results.extend(states_by_type[state_type])

    return results


@mcp.tool()
def get_my_issues(
    name: str,
    state_type: str | None = None,
    updated_after: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """
    Get issues assigned to a user with pagination.

    Returns a compact summary with issue identifiers, titles, and priorities.
    Use get_issue(identifier) to get full details of a specific issue.

    Args:
        name: User name to search for
        state_type: Optional filter by state type (started, unstarted, completed, canceled, backlog)
        updated_after: Filter to issues updated after this ISO-8601 datetime (e.g., '2024-01-01T00:00:00Z')
        limit: Maximum number of issues to return (default 20, max 100)
        cursor: Pagination cursor from previous response (issue ID to start after)

    Returns:
        Dictionary with user info, counts by state, and paginated issues
    """
    reader = get_reader()
    limit = min(limit, 100)

    # Parse updated_after filter
    updated_after_ts = None
    if updated_after:
        updated_after_ts = _parse_datetime(updated_after)
        if updated_after_ts is None:
            return {"error": f"Invalid updated_after format: {updated_after}"}

    user = reader.find_user(name)

    if not user:
        return {"error": f"User '{name}' not found"}

    # Get all issues for user, sorted by priority then ID for stable pagination
    all_issues = sorted(
        reader.get_issues_for_user(user["id"]),
        key=lambda x: (x.get("priority") or 4, x.get("id", "")),
    )

    # Count by state type
    counts_by_state: dict[str, int] = {}
    for issue in all_issues:
        issue_state_type = reader.get_state_type(issue.get("stateId", ""))
        counts_by_state[issue_state_type] = counts_by_state.get(issue_state_type, 0) + 1

    # Filter by state_type if provided
    if state_type:
        all_issues = [
            i
            for i in all_issues
            if reader.get_state_type(i.get("stateId", "")) == state_type
        ]

    # Filter by updated_after if provided
    if updated_after_ts is not None:
        all_issues = [
            i
            for i in all_issues
            if (_parse_datetime(i.get("updatedAt")) or 0) >= updated_after_ts
        ]

    total_matching = len(all_issues)

    # Apply cursor
    if cursor:
        skip = True
        filtered_after_cursor = []
        for issue in all_issues:
            if skip:
                if issue.get("id") == cursor:
                    skip = False
                continue
            filtered_after_cursor.append(issue)
        all_issues = filtered_after_cursor

    # Take limit + 1 to check if there are more
    page = all_issues[: limit + 1]
    has_more = len(page) > limit
    page = page[:limit]

    # Get next cursor (already sorted by priority, ID)
    next_cursor = page[-1].get("id") if has_more and page else None

    results = []
    for issue in page:
        compact = {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "priority": issue.get("priority"),
            "state": reader.get_state_name(issue.get("stateId", "")),
            "stateType": reader.get_state_type(issue.get("stateId", "")),
        }
        results.append(compact)

    return {
        "user": {"name": user.get("name"), "email": user.get("email")},
        "totalIssues": sum(counts_by_state.values()),
        "countsByStateType": counts_by_state,
        "matchingCount": total_matching,
        "issues": results,
        "nextCursor": next_cursor,
    }


@mcp.tool()
def get_issue_comments(identifier: str) -> dict[str, Any]:
    """
    Get all comments for an issue.

    Args:
        identifier: Issue identifier like 'T-1234' or 'EMA-567'

    Returns:
        Dictionary with issue info and list of comments with author names
    """
    reader = get_reader()
    issue = reader.get_issue_by_identifier(identifier)

    if not issue:
        return {"error": f"Issue '{identifier}' not found"}

    comments = reader.get_comments_for_issue(issue["id"])

    enriched_comments = []
    for comment in comments:
        user = reader.users.get(comment.get("userId", ""), {})
        enriched_comments.append(
            {
                "id": comment.get("id"),
                "author": user.get("name", "Unknown"),
                "body": comment.get("body", ""),
                "createdAt": comment.get("createdAt"),
            }
        )

    return {
        "issue": {
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
        },
        "commentCount": len(enriched_comments),
        "comments": enriched_comments,
    }


@mcp.tool()
def get_summary() -> dict[str, Any]:
    """
    Get a summary of the Linear local data.

    Returns:
        Dictionary with counts of teams, users, states, issues, and comments
    """
    reader = get_reader()
    return reader.get_summary()


def main():
    """Run the MCP server."""
    mcp.run()
