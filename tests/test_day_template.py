import ast
import importlib.util
import re
import runpy
from pathlib import Path

import pytest

import elf
from elf.exceptions import TemplateCreationError
from elf.scaffold import create_day_template, render_day_template

TEMPLATE = Path(__file__).parents[1] / "elf" / "templates" / "day_template.py"
CELL_MARKERS = [
    "# %% Setup",
    "# %% Load Input",
    "# %% Parse Input",
    "# %% Explore",
    "# %% Part 1",
    "# %% Part 2",
    "# %% Submit Answers",
]


def _mock_template_api(monkeypatch):
    submissions = []
    monkeypatch.setattr(elf, "get_puzzle_input", lambda year, day: "10\n20\n")
    monkeypatch.setattr(
        elf,
        "submit_puzzle_answer",
        lambda *args, **kwargs: submissions.append((args, kwargs)),
    )
    return submissions


def test_template_is_valid_python_with_expected_cells_and_api_usage():
    source = TEMPLATE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TEMPLATE))

    assert [line for line in source.splitlines() if line.startswith("# %%")] == CELL_MARKERS
    assert "from elf import get_puzzle_input" in source
    assert "# from elf import submit_puzzle_answer" in source
    assert "raw = sample if USE_SAMPLE else get_puzzle_input(YEAR, DAY)" in source
    assert "# part1_submission = submit_puzzle_answer(YEAR, DAY, 1, part1_answer)" in source
    assert "# part2_submission = submit_puzzle_answer(YEAR, DAY, 2, part2_answer)" in source

    called_names = {
        call.func.id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }
    assert "get_puzzle_input" in called_names
    assert "submit_puzzle_answer" not in called_names


def test_template_renderer_sets_year_and_day():
    source = render_day_template(2024, 25)

    ast.parse(source)
    assert "YEAR = 2024" in source
    assert "DAY = 25" in source


def test_template_sample_mode_does_not_fetch_real_input(monkeypatch, capsys):
    source = render_day_template(2025, 1)
    source = source.replace("USE_SAMPLE = False", "USE_SAMPLE = True", 1)
    source = source.replace('sample = """\\\n""".strip()', 'sample = """\\\n1\n2\n""".strip()', 1)
    monkeypatch.setattr(
        elf,
        "get_puzzle_input",
        lambda *args, **kwargs: pytest.fail("Sample mode fetched the real puzzle input."),
    )
    namespace = {"__name__": "__main__"}

    exec(compile(source, "day01.py", "exec"), namespace)

    assert namespace["raw"] == "1\n2"
    assert namespace["lines"] == ["1", "2"]
    assert namespace["data"] == ["1", "2"]
    assert capsys.readouterr().out == "Part 1: None\nPart 2: None\n"


def test_template_creation_uses_default_name_and_refuses_overwrite(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    destination = create_day_template(2025, 2)

    assert destination == Path("2025/day02.py")
    assert "YEAR = 2025" in destination.read_text(encoding="utf-8")
    assert "DAY = 2" in destination.read_text(encoding="utf-8")
    with pytest.raises(TemplateCreationError, match="Refusing to overwrite"):
        create_day_template(2025, 2)


def test_template_creation_supports_nested_output_and_validates_day(tmp_path):
    destination = tmp_path / "solutions" / "day01.py"

    assert create_day_template(2025, 1, destination) == destination
    assert destination.is_file()
    with pytest.raises(TemplateCreationError, match="days 1–12"):
        create_day_template(2025, 13, tmp_path / "day13.py")


def test_template_runs_as_a_script_with_visible_unsolved_variables(monkeypatch, capsys):
    submissions = _mock_template_api(monkeypatch)

    namespace = runpy.run_path(str(TEMPLATE), run_name="__main__")

    assert namespace["raw"] == "10\n20\n"
    assert namespace["lines"] == ["10", "20"]
    assert namespace["data"] == ["10", "20"]
    assert namespace["sample"] == ""
    assert namespace["USE_SAMPLE"] is False
    assert namespace["part1_answer"] is None
    assert namespace["part2_answer"] is None
    assert submissions == []
    assert capsys.readouterr().out == "Part 1: None\nPart 2: None\n"


def test_template_cells_share_an_interactive_namespace(monkeypatch, capsys):
    submissions = _mock_template_api(monkeypatch)
    source = TEMPLATE.read_text(encoding="utf-8")
    cells = [cell for cell in re.split(r"(?=^# %% )", source, flags=re.MULTILINE) if cell]
    namespace = {"__name__": "__main__"}

    for cell in cells:
        exec(compile(cell, str(TEMPLATE), "exec"), namespace)

    assert namespace["raw"] == "10\n20\n"
    assert namespace["lines"] == ["10", "20"]
    assert namespace["data"] == ["10", "20"]
    assert namespace["sample"] == ""
    assert namespace["part1_answer"] is None
    assert namespace["part2_answer"] is None
    assert submissions == []
    assert capsys.readouterr().out == "Part 1: None\nPart 2: None\n"


def test_importing_template_never_submits_answers(monkeypatch, capsys):
    submissions = _mock_template_api(monkeypatch)
    spec = importlib.util.spec_from_file_location("elf_day_template", TEMPLATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.part1_answer is None
    assert module.part2_answer is None
    assert submissions == []
    assert capsys.readouterr().out == "Part 1: None\nPart 2: None\n"
