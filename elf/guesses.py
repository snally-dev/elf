from datetime import UTC, datetime
from pathlib import Path

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .cache import get_cache_dir, get_cache_guess_file
from .exceptions import ElfError
from .models import Guess, SubmissionStatus
from .utils import read_guesses


def get_guesses(year: int, day: int, session: str | None = None) -> Group:
    cache_file = _resolve_guess_file(year, day, session)
    if not cache_file.exists():
        raise ElfError(
            f"No cached guesses found yet for {year}-12-{day:02d}. "
            "Submit an answer before viewing guess history."
        )
    cached_guesses = read_guesses(year, day, session_token=session, cache_file=cache_file)

    return render_guess_tables(cached_guesses)


def _resolve_guess_file(year: int, day: int, session: str | None) -> Path:
    if session:
        return get_cache_guess_file(year, day, session)

    legacy_file = get_cache_guess_file(year, day)
    if legacy_file.exists():
        return legacy_file

    pattern = f"accounts/*/{year:04d}/{day:02d}/guesses.csv"
    matches = list(get_cache_dir().glob(pattern))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ElfError(
            "Guess history exists for multiple accounts. "
            "Set AOC_SESSION or pass --session to choose one."
        )
    return legacy_file


def render_guess_tables(guesses: list[Guess]) -> Group:
    # normalize datetimes
    guesses = sorted(guesses, key=lambda g: _ensure_aware(g.timestamp))

    # split
    part1 = [g for g in guesses if g.part == 1]
    part2 = [g for g in guesses if g.part == 2]

    table1 = _render_single_table(part1, title="Guess History – Part 1")
    table2 = _render_single_table(part2, title="Guess History – Part 2")

    # Rich will print these back-to-back in order
    return Group(table1, table2)


def _render_single_table(guesses: list[Guess], title: str) -> Table:
    table = Table(title=title)

    table.add_column("Time (UTC)", style="cyan")
    table.add_column("Guess", justify="right", style="yellow")
    table.add_column("Status", style="green")

    for guess in guesses:
        ts = _ensure_aware(guess.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        if guess.status is SubmissionStatus.CORRECT:
            status_text = Text("Correct", style="bold green")
        elif guess.status is SubmissionStatus.COMPLETED:
            status_text = Text("Completed", style="bold green")
        elif guess.status is SubmissionStatus.UNKNOWN:
            status_text = Text("Unknown", style="yellow")
        elif guess.status is SubmissionStatus.INCORRECT:
            status_text = Text("Incorrect", style="red")
        elif guess.status is SubmissionStatus.WAIT:
            if guess.retry_at is None:
                label = "Wait"
            else:
                retry_at = _ensure_aware(guess.retry_at).strftime("%H:%M:%S UTC")
                label = f"Wait until {retry_at}"
            status_text = Text(label, style="magenta")
        elif guess.status is SubmissionStatus.TOO_HIGH:
            status_text = Text("Too High", style="purple")
        elif guess.status is SubmissionStatus.TOO_LOW:
            status_text = Text("Too Low", style="blue")
        else:
            status_text = Text(guess.status.value)

        table.add_row(ts, Text(str(guess.guess)), status_text)

    return table


def _ensure_aware(dt: datetime) -> datetime:
    """Make any datetime UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
