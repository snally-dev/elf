import httpx

from .aoc_client import AOCClient
from .cache import (
    atomic_write_text,
    get_cache_input_file,
    migrate_legacy_cache_file,
)
from .events import validate_event_day
from .exceptions import InputFetchError, PuzzleLockedError
from .utils import (
    current_aoc_year,
    get_unlock_status,
    handle_http_errors,
    looks_like_login_content,
    looks_like_login_page,
    resolve_session,
)


def get_input(year: int, day: int, session: str | None) -> str:
    """
    Fetch and cache the Advent of Code puzzle input for a specific year and day.

    Args:
        year: The year of the Advent of Code challenge.
        day: The day of the Advent of Code challenge.
        session: Your Advent of Code session token, or None to signal missing.

    Returns:
        The puzzle input for the specified day. Uses the cache if available.

    Raises:
        MissingSessionTokenError: If no session token was provided.
        InputFetchError: If there is an issue fetching the puzzle input.
        ValueError: If the year/day are out of range.
    """
    validate_event_day(year, day)

    session_token = resolve_session(session)
    legacy_cache_file = get_cache_input_file(year, day)
    cache_file = get_cache_input_file(year, day, session_token)

    try:
        migrate_legacy_cache_file(legacy_cache_file, cache_file)
        if cache_file.exists():
            cached_input = cache_file.read_text(encoding="utf-8")
            if not looks_like_login_content(cached_input):
                return cached_input
    except (OSError, UnicodeError):
        # A damaged or inaccessible cache should not prevent a fresh fetch.
        pass

    if year >= current_aoc_year():
        status = get_unlock_status(year, day)
        if not status.unlocked:
            raise PuzzleLockedError(
                year=year,
                day=day,
                now=status.now,
                unlock_time=status.unlock_time,
            )

    # --- Network layer --------------------------------------------------------

    try:
        with AOCClient(session_token=session_token) as client:
            response = client.fetch_input(year, day)

    except httpx.TimeoutException as exc:
        raise InputFetchError(
            "Timed out while fetching puzzle input. Try again or check your network."
        ) from exc

    except httpx.RequestError as exc:
        raise InputFetchError(f"Network error while connecting to Advent of Code: {exc}") from exc

    # --- HTTP status handling -------------------------------------------------
    handle_http_errors(
        response,
        exc_cls=InputFetchError,
        not_found_message=f"Input not found for year={year}, day={day} (HTTP 404).",
        bad_request_message="Bad request (HTTP 400). Your session token may be invalid.",
        server_error_message=(
            "Server error from Advent of Code (HTTP {status_code}). "
            "Your session token may be invalid."
        ),
        unexpected_status_message="Unexpected HTTP error: {status_code}.",
    )

    text = response.text

    if looks_like_login_page(response):
        raise InputFetchError(
            "Session cookie invalid or expired. "
            "Update AOC_SESSION with a valid 'session' cookie from your browser."
        )

    input_data = text

    try:
        atomic_write_text(cache_file, input_data)
    except OSError as exc:
        raise InputFetchError(f"Failed to cache puzzle input at {cache_file}.") from exc

    return input_data
