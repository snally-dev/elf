from elf.models import DayStatus, OutputFormat, SubmissionResult, SubmissionStatus


def test_output_format_members_cover_known_values():
    assert set(OutputFormat) == {
        OutputFormat.CSV,
        OutputFormat.JSON,
        OutputFormat.MODEL,
        OutputFormat.TABLE,
    }


def test_day_status_new_field_is_backward_compatible():
    status = DayStatus(day=1, stars=2, href="/2025/day/1", aria_label="Day 1, two stars")

    assert status.is_locked is False


def test_submission_status_has_known_members():
    # These are the statuses already referenced by your tests.
    members = {status for status in SubmissionStatus}

    assert SubmissionStatus.CORRECT in members
    assert SubmissionStatus.INCORRECT in members
    assert SubmissionStatus.TOO_LOW in members
    # WAIT is used in the CLI exit-code logic.
    assert SubmissionStatus.WAIT in members


def test_submission_result_correct_flag_consistency():
    """
    Sanity check: a SubmissionResult constructed with CORRECT should be marked
    as correct, and anything else should not be.
    (This matches how you already construct SubmissionResult in CLI tests.)
    """
    correct = SubmissionResult(
        guess="42",
        result=SubmissionStatus.CORRECT,
        message="ok",
        is_correct=True,
        is_cached=False,
    )
    wait = SubmissionResult(
        guess="42",
        result=SubmissionStatus.WAIT,
        message="wait",
        is_correct=False,
        is_cached=False,
    )

    assert correct.result == SubmissionStatus.CORRECT
    assert correct.is_correct is True

    assert wait.result == SubmissionStatus.WAIT
    assert wait.is_correct is False
