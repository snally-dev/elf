from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, StrEnum, auto

from pydantic import BaseModel, ConfigDict, Field


class StarCompletion(BaseModel):
    """Single star completion (per day/part)."""

    model_config = ConfigDict(extra="ignore")

    get_star_ts: int = Field(
        ...,
        description="Unix timestamp when this star was acquired.",
    )
    star_index: int = Field(
        ...,
        description="Position in the leaderboard when the star was acquired.",
    )


class Member(BaseModel):
    """A single leaderboard member."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    last_star_ts: int
    stars: int
    local_score: int
    completion_day_level: dict[int, dict[int, StarCompletion]] = Field(
        default_factory=dict,
        description="Mapping of day -> part -> StarCompletion.",
    )


class Leaderboard(BaseModel):
    """Top-level Advent of Code leaderboard object."""

    model_config = ConfigDict(extra="ignore")

    num_days: int
    event: str
    day1_ts: int
    owner_id: int
    # member_id -> Member (keys in JSON are numeric strings; parsed as ints)
    members: dict[int, Member]


class SubmissionStatus(StrEnum):
    CORRECT = auto()
    INCORRECT = auto()
    TOO_HIGH = auto()
    TOO_LOW = auto()
    WAIT = auto()
    COMPLETED = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Outcome of an answer attempt, including a cooldown deadline when applicable."""

    guess: int | str
    result: SubmissionStatus
    message: str
    is_correct: bool
    is_cached: bool
    retry_at: datetime | None = None

    def __repr__(self):
        return (
            f"SubmissionResult(\n"
            f"  guess={self.guess!r},\n"
            f"  result={self.result.name},\n"
            f"  is_correct={self.is_correct},\n"
            f"  is_cached={self.is_cached},\n"
            f"  retry_at={self.retry_at!r},\n"
            f"  message={self.message!r}\n"
            f")"
        )


@dataclass(slots=True)
class Guess:
    timestamp: datetime
    part: int
    guess: int | str
    status: SubmissionStatus
    retry_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CachedGuessCheck:
    guess: int | str
    previous_guess: int | str | None
    previous_timestamp: datetime | None
    status: SubmissionStatus
    message: str
    retry_at: datetime | None = None


@dataclass(slots=True)
class UnlockStatus:
    unlocked: bool
    now: datetime
    unlock_time: datetime


class OutputFormat(str, Enum):
    MODEL = "model"
    TABLE = "table"
    JSON = "json"


class OpenKind(str, Enum):
    WEBSITE = "website"
    PUZZLE = "puzzle"
    INPUT = "input"


class DayStatus(BaseModel):
    day: int = Field(..., ge=1, le=31)
    stars: int = Field(..., ge=0, le=2)
    href: str
    aria_label: str
    is_locked: bool

    model_config = {
        "frozen": True,  # makes objects hashable/immutable
        "extra": "forbid",  # catch unexpected fields
        "populate_by_name": True,
    }


class YearStatus(BaseModel):
    year: int = Field(..., ge=2015)
    username: str
    is_supporter: bool
    total_stars: int = Field(..., ge=0)
    days: list[DayStatus]

    model_config = {
        "frozen": True,
        "extra": "forbid",
        "populate_by_name": True,
    }
