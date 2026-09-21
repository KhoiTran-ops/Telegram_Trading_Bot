from datetime import datetime
from zoneinfo import ZoneInfo

from reporting.notifier import due_session


VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")


def test_due_session_only_fires_once_per_session() -> None:
    sent: set[tuple[str, str]] = set()
    morning = datetime(2026, 9, 21, 11, 36, tzinfo=VIETNAM)
    assert due_session(morning, sent) == "MORNING"
    sent.add(("2026-09-21", "MORNING"))
    assert due_session(morning, sent) is None
    assert due_session(datetime(2026, 9, 21, 15, 6, tzinfo=VIETNAM), sent) == "FULL_DAY"


def test_due_session_skips_weekends() -> None:
    assert due_session(datetime(2026, 9, 20, 15, 6, tzinfo=VIETNAM), set()) is None
