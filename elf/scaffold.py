from importlib.resources import files
from pathlib import Path

from .events import validate_event_day
from .exceptions import TemplateCreationError

_TEMPLATE = "templates/day_template.py"


def render_day_template(year: int, day: int) -> str:
    """Render the canonical interactive template for a puzzle."""
    try:
        validate_event_day(year, day)
    except ValueError as exc:
        raise TemplateCreationError(str(exc)) from exc

    template = files("elf").joinpath(_TEMPLATE).read_text(encoding="utf-8")
    return template.replace("YEAR = 2025", f"YEAR = {year}", 1).replace(
        "DAY = 1", f"DAY = {day}", 1
    )


def create_day_template(year: int, day: int, output: Path | None = None) -> Path:
    """Create a puzzle file without overwriting an existing path."""
    destination = output or Path(str(year)) / f"day{day:02d}.py"
    source = render_day_template(year, day)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8", newline="\n") as template_file:
            template_file.write(source)
    except FileExistsError as exc:
        raise TemplateCreationError(f"Refusing to overwrite existing path: {destination}") from exc
    except OSError as exc:
        raise TemplateCreationError(
            f"Could not create puzzle template at {destination}: {exc}"
        ) from exc

    return destination
