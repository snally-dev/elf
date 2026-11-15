import csv
import json
import os
import time
import warnings
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from rich.table import Table
from rich.text import Text

from .aoc_client import AOCClient
from .cache import (
    CacheLockTimeoutError,
    atomic_write_text,
    cache_file_lock,
    get_cache_leaderboard_file,
)
from .exceptions import LeaderboardFetchError, MissingSessionTokenError
from .models import Leaderboard, Member, OutputFormat
from .utils import handle_http_errors, resolve_session

LEADERBOARD_CACHE_TTL = timedelta(minutes=15)


def get_leaderboard(
    year: int,
    session: str | None,
    board_id: int,
    view_key: str | None,
    fmt: OutputFormat = OutputFormat.MODEL,
) -> Leaderboard | str | Table:
    """
    Fetch a private leaderboard for a specific year.

    Args:
        year: The year of the Advent of Code challenge.
        session: Your Advent of Code session token (optional if view_key is supplied).
        board_id: The ID of the private leaderboard.
        view_key: The view key for the private leaderboard, if required.
    """

    if year < 2015:
        raise ValueError(f"Invalid year {year!r}. Advent of Code started in 2015.")

    if board_id <= 0:
        raise ValueError("Board ID must be a positive integer.")

    # Resolve session token from explicit arg or environment for consistency with other APIs.
    session_token = (
        resolve_session(session) if view_key is None else session or os.getenv("AOC_SESSION")
    )
    if not session_token and not view_key:
        raise MissingSessionTokenError(env_var="AOC_SESSION")

    cache_file = get_cache_leaderboard_file(
        year,
        board_id,
        session_token=session_token,
        view_key=view_key,
    )
    payload = _read_fresh_cache(cache_file)

    if payload is None:
        try:
            with cache_file_lock(cache_file, timeout=60.0, stale_after=120.0):
                payload = _read_fresh_cache(cache_file)
                if payload is None:
                    payload = _fetch_leaderboard_payload(
                        year=year,
                        board_id=board_id,
                        session_token=session_token,
                        view_key=view_key,
                    )
                    try:
                        atomic_write_text(
                            cache_file,
                            json.dumps(payload, separators=(",", ":")),
                        )
                    except OSError as exc:
                        warnings.warn(
                            f"Could not write leaderboard cache {cache_file}: {exc}",
                            RuntimeWarning,
                            stacklevel=2,
                        )
        except CacheLockTimeoutError as exc:
            raise LeaderboardFetchError(
                "Timed out waiting for another elf process to refresh the leaderboard cache."
            ) from exc

    leaderboard = _validate_leaderboard(payload)

    match fmt:
        case OutputFormat.MODEL:
            return leaderboard
        case OutputFormat.JSON:
            return json.dumps(payload, indent=2)
        case OutputFormat.CSV:
            return format_leaderboard_as_csv(leaderboard, year=year, board_id=board_id)
        case OutputFormat.TABLE:
            return format_leaderboard_as_table(leaderboard)
        case _:
            raise ValueError(f"Unsupported output format: {fmt}")


def _fetch_leaderboard_payload(
    *,
    year: int,
    board_id: int,
    session_token: str | None,
    view_key: str | None,
) -> dict[str, Any]:
    """Fetch and decode a private leaderboard response."""

    try:
        with AOCClient(session_token=session_token) as client:
            response = client.fetch_leaderboard(year, board_id, view_key)
    except httpx.TimeoutException as exc:
        raise LeaderboardFetchError(
            "Timed out while fetching leaderboard. Try again or check your network."
        ) from exc
    except httpx.RequestError as exc:
        raise LeaderboardFetchError(
            f"Network error while connecting to Advent of Code: {exc}"
        ) from exc

    handle_http_errors(
        response,
        exc_cls=LeaderboardFetchError,
        not_found_message=f"Leaderboard not found for year={year}, board_id={board_id} (HTTP 404).",
        bad_request_message=(
            "Bad request (HTTP 400). Your session token or view key may be invalid."
        ),
        server_error_message=(
            "Server error from Advent of Code (HTTP {status_code}). "
            "Your session token may be invalid."
        ),
        unexpected_status_message="Unexpected HTTP error: {status_code}.",
    )

    try:
        payload = response.json()
    except ValueError as exc:
        raise LeaderboardFetchError(
            "Failed to decode leaderboard JSON. Your session/view key may be invalid."
        ) from exc

    if not isinstance(payload, dict):
        raise LeaderboardFetchError("Unexpected leaderboard schema from Advent of Code.")
    _validate_leaderboard(payload)
    return payload


def _read_fresh_cache(cache_file: Path) -> dict[str, Any] | None:
    """Return a valid cache entry within AoC's 15-minute request interval."""
    try:
        age_seconds = time.time() - cache_file.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LeaderboardFetchError(f"Could not inspect leaderboard cache {cache_file}.") from exc

    if age_seconds > LEADERBOARD_CACHE_TTL.total_seconds():
        return None

    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Leaderboard cache must contain a JSON object.")
        _validate_leaderboard(payload)
        return payload
    except (OSError, ValueError, ValidationError, LeaderboardFetchError) as exc:
        raise LeaderboardFetchError(
            "The fresh leaderboard cache is unreadable or malformed. "
            "Elf will not request the leaderboard again within AoC's 15-minute interval; "
            f"retry after the interval has elapsed. Cache: {cache_file}."
        ) from exc


def _validate_leaderboard(payload: dict[str, Any]) -> Leaderboard:
    try:
        return Leaderboard.model_validate(payload)
    except ValidationError as exc:
        raise LeaderboardFetchError("Unexpected leaderboard schema from Advent of Code.") from exc


def _first_star_timestamp(member: Member) -> int | None:
    """Return the member's earliest star completion timestamp, if any."""
    return min(
        (
            completion.get_star_ts
            for parts in member.completion_day_level.values()
            for completion in parts.values()
        ),
        default=None,
    )


def _format_utc_timestamp(timestamp: int | None) -> str:
    if not timestamp:
        return "-"
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")


def _format_csv_timestamp(timestamp: int | None) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ranked_members(leaderboard: Leaderboard) -> list[Member]:
    return sorted(
        leaderboard.members.values(),
        key=lambda member: (-member.local_score, -member.stars, member.id),
    )


def format_leaderboard_as_csv(
    leaderboard: Leaderboard,
    *,
    year: int,
    board_id: int,
) -> str:
    """Serialize one deterministic summary row per leaderboard member."""
    output = StringIO(newline="")
    fieldnames = (
        "year",
        "board_id",
        "rank",
        "member_id",
        "name",
        "stars",
        "local_score",
        "first_star_utc",
        "last_star_utc",
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    for rank, member in enumerate(_ranked_members(leaderboard), start=1):
        writer.writerow(
            {
                "year": year,
                "board_id": board_id,
                "rank": rank,
                "member_id": member.id,
                "name": member.name or "<anonymous>",
                "stars": member.stars,
                "local_score": member.local_score,
                "first_star_utc": _format_csv_timestamp(_first_star_timestamp(member)),
                "last_star_utc": _format_csv_timestamp(member.last_star_ts),
            }
        )

    return output.getvalue()


def format_leaderboard_as_table(leaderboard: Leaderboard) -> Table:
    table = Table(title=Text(f"Advent of Code {leaderboard.event} – Private Leaderboard"))

    table.add_column("Rank", justify="right", style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Stars", justify="right", style="yellow")
    table.add_column("Local Score", justify="right", style="green")
    table.add_column("First Star (UTC)", style="magenta")
    table.add_column("Last Star (UTC)", style="magenta")

    for rank, member in enumerate(_ranked_members(leaderboard), start=1):
        table.add_row(
            str(rank),
            Text(member.name or "<anonymous>"),
            str(member.stars),
            str(member.local_score),
            _format_utc_timestamp(_first_star_timestamp(member)),
            _format_utc_timestamp(member.last_star_ts),
        )

    return table
