import csv
import io
import re
import warnings
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from html.parser import HTMLParser

import httpx

from .aoc_client import AOCClient
from .cache import (
    CacheLockTimeoutError,
    atomic_write_text,
    cache_file_lock,
    get_cache_guess_file,
    migrate_legacy_cache_file,
)
from .events import validate_event_day
from .exceptions import PuzzleLockedError, SubmissionError
from .messages import (
    get_already_completed_message,
    get_answer_too_high_message,
    get_answer_too_low_message,
    get_cached_duplicate_message,
    get_cached_high_message,
    get_cached_low_message,
    get_correct_answer_message,
    get_incorrect_answer_message,
    get_recent_submission_message,
    get_unexpected_response_message,
    get_wrong_level_message,
)
from .models import CachedGuessCheck, Guess, SubmissionResult, SubmissionStatus
from .utils import (
    current_aoc_year,
    get_unlock_status,
    looks_like_login_content,
    read_guesses,
    resolve_session,
)

WAIT_CACHE_TTL = timedelta(minutes=1)
_WAIT_TIME_PATTERN = re.compile(r"You have (?:(\d+)m )?(\d+)s left to wait")
_GUESS_CACHE_FIELDS = ["timestamp", "part", "guess", "status", "retry_at"]
_REQUIRED_GUESS_CACHE_FIELDS = {"timestamp", "part", "guess", "status"}


class AocResponseParser(HTMLParser):
    """Extract text inside the <article> tag."""

    def __init__(self) -> None:
        super().__init__()
        self.in_article: bool = False
        self.content: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article":
            self.in_article = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            self.in_article = False

    def handle_data(self, data: str) -> None:
        if self.in_article:
            self.content.append(data)

    def text(self) -> str:
        return "".join(self.content).strip()


class AocMessageType(Enum):
    EMPTY = auto()
    CORRECT = auto()
    TOO_HIGH = auto()
    TOO_LOW = auto()
    RECENT_SUBMISSION = auto()
    ALREADY_COMPLETED = auto()
    INCORRECT = auto()
    WRONG_LEVEL = auto()
    UNEXPECTED = auto()


def classify_message(content: str) -> AocMessageType:
    if not content:
        return AocMessageType.EMPTY

    checks: list[tuple[str, AocMessageType]] = [
        ("That's the right answer", AocMessageType.CORRECT),
        ("too high", AocMessageType.TOO_HIGH),
        ("too low", AocMessageType.TOO_LOW),
        ("You gave an answer too recently", AocMessageType.RECENT_SUBMISSION),
        ("Did you already complete it", AocMessageType.ALREADY_COMPLETED),
        ("You don't seem to be solving the right level", AocMessageType.WRONG_LEVEL),
        ("That's not the right answer", AocMessageType.INCORRECT),
    ]

    for needle, msg_type in checks:
        if needle in content:
            return msg_type

    return AocMessageType.UNEXPECTED


def submit_answer(
    year: int,
    day: int,
    level: int,
    answer: int | str,
    session: str | None,
) -> SubmissionResult:
    """
    Submit an answer for a specific Advent of Code day/part, with guess caching.

    Args:
        year: The year of the Advent of Code challenge.
        day: The day of the Advent of Code challenge.
        level: Puzzle part (1 or 2).
        answer: The answer to submit (int or string).
        session: Your Advent of Code session token, or None to signal missing.

    Returns:
        A SubmissionResult describing the outcome, including whether it was
        served from the local guess cache or from Advent of Code. Cooldown
        results include the exact retry deadline when AoC provides one.

    Raises:
        MissingSessionTokenError: If no session token was provided.
        SubmissionError: If there is an issue submitting the answer.
    """
    submission_answer, numeric_answer = _normalize_answer(answer)

    validate_event_day(year, day)

    if level not in (1, 2):
        raise ValueError(f"Invalid level {level!r}. Puzzle parts are 1 or 2.")

    if isinstance(answer, str) and not answer.strip():
        raise ValueError("Answer cannot be empty.")

    if year >= current_aoc_year():
        status = get_unlock_status(year, day)
        if not status.unlocked:
            raise PuzzleLockedError(
                year=year,
                day=day,
                now=status.now,
                unlock_time=status.unlock_time,
            )

    session_token = resolve_session(session)

    legacy_cache_file = get_cache_guess_file(year, day)
    cache_file = get_cache_guess_file(year, day, session_token)
    try:
        migrate_legacy_cache_file(legacy_cache_file, cache_file)
    except OSError as exc:
        raise SubmissionError(f"Failed to migrate guess cache at {legacy_cache_file}.") from exc

    # Serialize the cache check and submission for this account and puzzle. This
    # prevents two elf processes from both submitting before either records the
    # result. Guess-cache writes use their own shorter-lived lock.
    submission_lock = cache_file.with_name(f"{cache_file.name}.submission")
    try:
        with cache_file_lock(submission_lock, timeout=30.0, stale_after=60.0):
            if cache_file.exists():
                cached = check_cached_guesses(
                    year=year,
                    day=day,
                    level=level,
                    answer=submission_answer,
                    numeric_answer=numeric_answer,
                    session_token=session_token,
                )

                if cached.status != SubmissionStatus.UNKNOWN:
                    return SubmissionResult(
                        guess=submission_answer,
                        result=cached.status,
                        message=cached.message,
                        is_correct=cached.status == SubmissionStatus.CORRECT,
                        is_cached=True,
                        retry_at=cached.retry_at,
                    )

            return submit_to_aoc(year, day, level, submission_answer, session_token)
    except CacheLockTimeoutError as exc:
        raise SubmissionError(
            "Timed out waiting for another elf process to finish submitting an answer."
        ) from exc


def submit_to_aoc(
    year: int,
    day: int,
    level: int,
    answer: int | str,
    session_token: str,
) -> SubmissionResult:
    # --- Network layer --------------------------------------------------------

    try:
        with AOCClient(session_token=session_token) as client:
            response = client.submit_answer(year, day, str(answer), level)
    except httpx.TimeoutException as exc:
        raise SubmissionError(
            "Timed out while submitting answer. Try again or check your network."
        ) from exc

    except httpx.RequestError as exc:
        raise SubmissionError(f"Network error while connecting to Advent of Code: {exc}") from exc

    # --- HTTP status handling -------------------------------------------------

    if response.status_code == 404:
        if "unlocks it for you" in response.text:
            raise SubmissionError("Puzzle not yet unlocked.")
        elif "Please don't repeatedly request this endpoint" in response.text:
            raise SubmissionError(
                "Submitting answers too quickly. Please wait before trying again."
            )

        else:
            raise SubmissionError(
                f"Answer endpoint not found for year={year}, day={day} (HTTP 404)."
            )

    if response.status_code == 400:
        raise SubmissionError("Bad request (HTTP 400). Your session token may be invalid.")

    if 500 <= response.status_code < 600:
        raise SubmissionError(f"Server error from Advent of Code (HTTP {response.status_code}).")

    if response.status_code != 200:
        raise SubmissionError(f"Unexpected HTTP status {response.status_code} from Advent of Code.")

    if looks_like_login_content(response.text):
        raise SubmissionError(
            "Session cookie invalid or expired. "
            "Update AOC_SESSION with a valid 'session' cookie from your browser."
        )

    # Extract <article> content
    parser = AocResponseParser()
    parser.feed(response.text)
    content = parser.text()

    # Determine result type
    message_type = classify_message(content)
    retry_at: datetime | None = None
    match message_type:
        case AocMessageType.EMPTY:
            message = "Answer submitted, but no response message found."
            status = SubmissionStatus.UNKNOWN
        case AocMessageType.CORRECT:
            message = get_correct_answer_message(answer)
            status = SubmissionStatus.CORRECT
        case AocMessageType.TOO_HIGH:
            message = get_answer_too_high_message(answer)
            status = SubmissionStatus.TOO_HIGH
        case AocMessageType.TOO_LOW:
            message = get_answer_too_low_message(answer)
            status = SubmissionStatus.TOO_LOW
        case AocMessageType.RECENT_SUBMISSION:
            status = SubmissionStatus.WAIT
            retry_at = _parse_wait_retry_at(content) or datetime.now(UTC) + WAIT_CACHE_TTL
            message = _wait_message(retry_at, cached=False)
        case AocMessageType.ALREADY_COMPLETED:
            message = get_already_completed_message()
            status = SubmissionStatus.COMPLETED
        case AocMessageType.WRONG_LEVEL:
            message = get_wrong_level_message()
            status = SubmissionStatus.INCORRECT
        case AocMessageType.INCORRECT:
            message = get_incorrect_answer_message(answer)
            status = SubmissionStatus.INCORRECT
        case _:
            message = get_unexpected_response_message()
            status = SubmissionStatus.UNKNOWN

    # The request has already happened, so a local cache failure must not hide
    # Advent of Code's result and encourage an accidental retry.
    try:
        write_guess_cache(
            year,
            day,
            level,
            answer,
            status,
            session_token=session_token,
            retry_at=retry_at,
        )
    except RuntimeError as exc:
        warnings.warn(
            f"Answer was submitted, but elf could not update the guess cache: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )

    return SubmissionResult(
        guess=answer,
        result=status,
        message=message,
        is_correct=status == SubmissionStatus.CORRECT,
        is_cached=False,
        retry_at=retry_at,
    )


def write_guess_cache(
    year: int,
    day: int,
    part: int,
    guess: int | str,
    status: SubmissionStatus,
    session_token: str | None = None,
    retry_at: datetime | None = None,
) -> None:
    cache_file = get_cache_guess_file(year, day, session_token)

    timestamp = datetime.now(UTC).isoformat()
    canonical_guess, _ = _normalize_answer(guess)
    row = {
        "timestamp": timestamp,
        "part": part,
        "guess": str(canonical_guess),
        "status": status.name,
        "retry_at": retry_at.isoformat() if retry_at is not None else "",
    }

    try:
        with cache_file_lock(cache_file, timeout=10.0, stale_after=30.0):
            existing = cache_file.read_text(encoding="utf-8") if cache_file.exists() else ""
            atomic_write_text(cache_file, _updated_guess_cache(existing, row))
    except Exception as exc:
        raise RuntimeError(f"Failed to write guess cache {cache_file}: {exc}") from exc


def check_cached_guesses(
    year: int,
    day: int,
    level: int,
    answer: int | str,
    numeric_answer: int | None,
    session_token: str | None = None,
) -> CachedGuessCheck:
    guesses = read_guesses(year, day, session_token=session_token)
    now = datetime.now(UTC)

    highest_low: Guess | None = None
    lowest_high: Guess | None = None
    completed_guess: Guess | None = None
    wait_guess: Guess | None = None
    duplicate_guess: Guess | None = None

    for g in guesses:
        if g.part != level:
            continue

        # A later response supersedes an earlier local cooldown entry.
        if g.status is SubmissionStatus.WAIT and _wait_is_active(g, now):
            wait_guess = g
        elif wait_guess is not None and g.timestamp >= wait_guess.timestamp:
            wait_guess = None

        is_same_guess = g.guess == answer or (
            numeric_answer is not None and isinstance(g.guess, int) and g.guess == numeric_answer
        )

        # Remember the newest duplicate, but finish scanning so a later
        # successful solve can take precedence over an older failed guess.
        if is_same_guess and g.status != SubmissionStatus.WAIT:
            duplicate_guess = g

        match g:
            # A correct answer proves the part is complete just as surely as a
            # later "already completed" response.
            case Guess(status=SubmissionStatus.CORRECT | SubmissionStatus.COMPLETED):
                completed_guess = g

            # Bounds checking (int only)
            case Guess(guess=ans, status=SubmissionStatus.TOO_LOW) if (
                numeric_answer is not None and isinstance(ans, int)
            ):
                if highest_low is None or (
                    isinstance(highest_low.guess, int) and ans > highest_low.guess
                ):
                    highest_low = g
            case Guess(guess=ans, status=SubmissionStatus.TOO_HIGH) if (
                numeric_answer is not None and isinstance(ans, int)
            ):
                if lowest_high is None or (
                    isinstance(lowest_high.guess, int) and ans < lowest_high.guess
                ):
                    lowest_high = g

    # Preserve the familiar result for an exact cached correct answer.
    if duplicate_guess is not None and duplicate_guess.status is SubmissionStatus.CORRECT:
        return CachedGuessCheck(
            guess=answer,
            previous_guess=duplicate_guess.guess,
            previous_timestamp=duplicate_guess.timestamp,
            status=duplicate_guess.status,
            message=get_cached_duplicate_message(answer, duplicate_guess),
        )

    # Completion supersedes earlier cooldown, duplicate, and bounds entries.
    if completed_guess is not None:
        return CachedGuessCheck(
            guess=answer,
            previous_guess=None,
            previous_timestamp=completed_guess.timestamp,
            status=SubmissionStatus.COMPLETED,
            message=get_already_completed_message(),
        )

    if wait_guess is not None:
        retry_at = _retry_at(wait_guess)
        return CachedGuessCheck(
            guess=answer,
            previous_guess=None,
            previous_timestamp=wait_guess.timestamp,
            status=SubmissionStatus.WAIT,
            message=_wait_message(retry_at, cached=True),
            retry_at=retry_at,
        )

    if duplicate_guess is not None:
        return CachedGuessCheck(
            guess=answer,
            previous_guess=duplicate_guess.guess,
            previous_timestamp=duplicate_guess.timestamp,
            status=duplicate_guess.status,
            message=get_cached_duplicate_message(answer, duplicate_guess),
        )

    # Infer bounds
    if numeric_answer is not None:
        match (highest_low, lowest_high):
            case (h_low, _) if (
                h_low and isinstance(h_low.guess, int) and numeric_answer <= h_low.guess
            ):
                return CachedGuessCheck(
                    guess=answer,
                    previous_guess=h_low.guess,
                    previous_timestamp=h_low.timestamp,
                    status=SubmissionStatus.TOO_LOW,
                    message=get_cached_low_message(answer, h_low),
                )
            case (_, l_high) if (
                l_high and isinstance(l_high.guess, int) and numeric_answer >= l_high.guess
            ):
                return CachedGuessCheck(
                    guess=answer,
                    previous_guess=l_high.guess,
                    previous_timestamp=l_high.timestamp,
                    status=SubmissionStatus.TOO_HIGH,
                    message=get_cached_high_message(answer, l_high),
                )

    # No bounds found
    return CachedGuessCheck(
        guess=answer,
        previous_guess=None,
        previous_timestamp=None,
        status=SubmissionStatus.UNKNOWN,
        message="This is a unique guess.",
    )


def _updated_guess_cache(existing: str, row: dict[str, object]) -> str:
    """Append a row while upgrading old four-column CSV files safely."""
    fieldnames = list(_GUESS_CACHE_FIELDS)
    existing_rows: list[dict[str, str | None]] = []

    if existing:
        reader = csv.DictReader(io.StringIO(existing, newline=""))
        existing_fields = reader.fieldnames
        if (
            existing_fields is None
            or len(existing_fields) != len(set(existing_fields))
            or not _REQUIRED_GUESS_CACHE_FIELDS.issubset(existing_fields)
        ):
            raise ValueError("Guess cache has a malformed header; refusing to overwrite it.")
        fieldnames = list(existing_fields)
        if "retry_at" not in fieldnames:
            fieldnames.append("retry_at")
        for existing_row in reader:
            if None in existing_row:
                raise ValueError("Guess cache has a malformed row; refusing to overwrite it.")
            existing_rows.append(existing_row)

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(existing_rows)
    writer.writerow(row)
    return buffer.getvalue()


def _parse_wait_retry_at(content: str, *, now: datetime | None = None) -> datetime | None:
    match = _WAIT_TIME_PATTERN.search(content)
    if match is None:
        return None
    minutes = int(match.group(1) or 0)
    seconds = int(match.group(2))
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current + timedelta(minutes=minutes, seconds=seconds)


def _retry_at(guess: Guess) -> datetime:
    if guess.retry_at is not None:
        return (
            guess.retry_at
            if guess.retry_at.tzinfo is not None
            else guess.retry_at.replace(tzinfo=UTC)
        )
    timestamp = (
        guess.timestamp
        if guess.timestamp.tzinfo is not None
        else guess.timestamp.replace(tzinfo=UTC)
    )
    return timestamp + WAIT_CACHE_TTL


def _wait_is_active(guess: Guess, now: datetime) -> bool:
    return _retry_at(guess) > now


def _wait_message(retry_at: datetime, *, cached: bool) -> str:
    retry_str = retry_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    source = "Cached locally; " if cached else ""
    return f"{get_recent_submission_message()} {source}try again after {retry_str}."


def _normalize_answer(answer: int | str) -> tuple[int | str, int | None]:
    """
    Preserve answer text while providing a numeric variant for duplicate and bounds
    guardrails.

    Returns (submission_answer, numeric_answer).
    """
    if isinstance(answer, str):
        stripped = answer.strip()
        if not stripped:
            raise ValueError("Answer cannot be empty.")

        numeric_value: int | None = None
        if stripped.lstrip("+-").isdigit():
            try:
                numeric_value = int(stripped)
            except ValueError:
                numeric_value = None

        return stripped, numeric_value

    return answer, int(answer)
