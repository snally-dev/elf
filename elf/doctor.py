import os
import secrets
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from rich.table import Table
from rich.text import Text

from .aoc_client import _validate_user_agent
from .cache import get_cache_dir
from .constants import AOC_TZ, VERSION
from .events import default_event_day, default_event_year


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def has_errors(self) -> bool:
        return any(check.status is CheckStatus.ERROR for check in self.checks)


def run_doctor(*, now: datetime | None = None) -> DoctorReport:
    """Inspect local elf configuration without contacting Advent of Code."""
    current = now.astimezone(AOC_TZ) if now else datetime.now(tz=AOC_TZ)
    year = default_event_year(current)
    day = default_event_day(year, current)
    checks = [
        DoctorCheck("Version", CheckStatus.OK, f"elf {VERSION}"),
        DoctorCheck(
            "AoC clock",
            CheckStatus.OK,
            f"{current.isoformat(timespec='seconds')}; default puzzle {year}-12-{day:02d}",
        ),
        _session_check(),
        _user_agent_check(),
        _cache_check(get_cache_dir()),
    ]
    return DoctorReport(tuple(checks))


def format_doctor_report(report: DoctorReport) -> Table:
    table = Table(title="Elf doctor", show_lines=False)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Details")

    labels = {
        CheckStatus.OK: "[green]OK[/green]",
        CheckStatus.WARNING: "[yellow]WARNING[/yellow]",
        CheckStatus.ERROR: "[red]ERROR[/red]",
    }
    for check in report.checks:
        table.add_row(check.name, labels[check.status], Text(check.detail))
    return table


def _session_check() -> DoctorCheck:
    session = os.getenv("AOC_SESSION")
    if session and session.strip():
        return DoctorCheck(
            "Session",
            CheckStatus.OK,
            "AOC_SESSION is configured (value hidden).",
        )
    return DoctorCheck(
        "Session",
        CheckStatus.WARNING,
        "AOC_SESSION is not configured; authenticated commands will fail.",
    )


def _user_agent_check() -> DoctorCheck:
    value = os.getenv("AOC_USER_AGENT")
    sanitized = value.replace("\r", "").replace("\n", "").strip() if value else None
    if _validate_user_agent(sanitized):
        return DoctorCheck(
            "User-Agent",
            CheckStatus.OK,
            "AOC_USER_AGENT contains a contact email (value hidden).",
        )
    return DoctorCheck(
        "User-Agent",
        CheckStatus.WARNING,
        "Set AOC_USER_AGENT to a contact email recommended by Advent of Code.",
    )


def _cache_check(cache_dir: Path) -> DoctorCheck:
    probe = cache_dir / f".doctor-{secrets.token_hex(8)}"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, probe_name = tempfile.mkstemp(
            dir=cache_dir,
            prefix=probe.name,
        )
        os.close(descriptor)
        probe = Path(probe_name)
        probe.unlink()
        mode_detail = ""
        if os.name == "posix":
            mode = stat.S_IMODE(cache_dir.stat().st_mode)
            if mode & 0o077:
                return DoctorCheck(
                    "Cache",
                    CheckStatus.WARNING,
                    f"{cache_dir} is writable but permissions are {mode:04o}; expected 0700.",
                )
            mode_detail = f", permissions {mode:04o}"
        file_count = sum(1 for path in cache_dir.rglob("*") if path.is_file())
        return DoctorCheck(
            "Cache",
            CheckStatus.OK,
            f"{cache_dir} is writable ({file_count} cached files{mode_detail}).",
        )
    except OSError as exc:
        with suppress(OSError):
            probe.unlink(missing_ok=True)
        return DoctorCheck(
            "Cache",
            CheckStatus.ERROR,
            f"{cache_dir} is not writable: {exc}",
        )
