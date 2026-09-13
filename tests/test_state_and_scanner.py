import time

from umppa_monitor.browser import FetchResult, NetworkRecord
from umppa_monitor.config import ParserOverrides, ScheduleConfig, AppConfig, BrowserConfig
from umppa_monitor.models import Slot, SlotStatus, Target, TargetKind
from umppa_monitor.notify.format import format_opened
from umppa_monitor.scanner import apply_filters, is_notifiable, slots_from_result
from umppa_monitor.scheduler import in_quiet_hours
from umppa_monitor.state import StateStore, compute_diff, next_snapshot
from datetime import datetime

T = Target(kind=TargetKind.KIDSCAFE, id="X", name="X", weekdays=[5, 6], sessions=["2회차"], min_remaining=2)


def _slot(date, session, status, remaining=None):
    return Slot("kidscafe:X", TargetKind.KIDSCAFE, date, session, status, remaining)


def test_diff_transitions(tmp_path):
    store = StateStore(tmp_path)
    assert store.load("kidscafe:X") is None
    cur = [_slot("2026-09-19", "1회차", SlotStatus.FULL), _slot("2026-09-19", "2회차", SlotStatus.OPEN, 3)]
    d = compute_diff(None, cur)
    assert d.first_run and [s.session for s in d.opened] == ["2회차"]
    snap = next_snapshot(None, cur, [s.key for s in d.opened])
    store.save("kidscafe:X", snap)

    prev = store.load("kidscafe:X")
    assert prev and len(prev.slots) == 2 and prev.last_notified
    cur2 = [_slot("2026-09-19", "1회차", SlotStatus.OPEN, 1), _slot("2026-09-19", "2회차", SlotStatus.FULL, 0)]
    d2 = compute_diff(prev, cur2)
    assert [s.session for s in d2.opened] == ["1회차"]
    assert [s.session for s in d2.closed] == ["2회차"]
    assert d2.still_open == []
    # 사라진 슬롯도 closed 로
    d3 = compute_diff(prev, [])
    assert [s.session for s in d3.closed] == ["2회차"]


def test_filters_and_notifiable():
    slots = [
        _slot("2026-09-19", "2회차 11:00~12:50", SlotStatus.OPEN, 5),   # 토
        _slot("2026-09-19", "1회차 09:00~10:50", SlotStatus.OPEN, 5),   # 회차 필터 제외
        _slot("2026-09-21", "2회차 11:00~12:50", SlotStatus.OPEN, 5),   # 월 -> 요일 제외
        _slot("2026-09-20", "2회차 11:00~12:50", SlotStatus.OPEN, 1),   # 일, 잔여 부족
    ]
    f = apply_filters(slots, T)
    assert {(s.date, s.remaining) for s in f} == {("2026-09-19", 5), ("2026-09-20", 1)}
    assert is_notifiable(f[0], T) and not is_notifiable(f[1], T)
    t2 = Target(kind=TargetKind.KIDSCAFE, id="X", dates=["2026-09-21"])
    assert [s.date for s in apply_filters(slots, t2)] == ["2026-09-21"]


def test_slots_from_result_merges_sources():
    t = Target(kind=TargetKind.KIDSCAFE, id="X")
    cal = """<html><body><strong>2026년 9월</strong><table><tr><th>일</th><th>월</th><th>화</th><th>수</th><th>목</th><th>금</th><th>토</th></tr>
    <tr><td><em>19</em><a href="#">예약가능</a></td><td><em>20</em><span>마감</span></td></tr></table></body></html>"""
    slot_html = """<ul><li><button>1회차 09:00~10:50 잔여 0</button></li><li><button>2회차 11:00~12:50 잔여 4</button></li></ul>"""
    res = FetchResult(target=t, pages=[("u", cal)], slot_pages=[("2026-09-19", "u2", slot_html)],
                      network=[NetworkRecord("x.do", "POST", 200, None, "application/json", None,
                                             {"list": [{"resveDe": "20260920", "rmndrNmpr": 0}]})])
    slots = slots_from_result(res, ParserOverrides())
    keys = {(s.date, s.session): s.status for s in slots}
    # 19일은 회차 단위로 대체되고 day 슬롯은 제거
    assert ("2026-09-19", "day") not in keys
    assert keys[("2026-09-19", "2회차 11:00~12:50")] == SlotStatus.OPEN
    assert keys[("2026-09-19", "1회차 09:00~10:50")] == SlotStatus.FULL
    assert keys[("2026-09-20", "day")] == SlotStatus.FULL


def test_quiet_hours():
    cfg = AppConfig(targets=[T], notifiers=[], schedule=ScheduleConfig(quiet_hours=["23:00-06:30"]))
    assert in_quiet_hours(cfg, datetime(2026, 9, 13, 1, 0))
    assert in_quiet_hours(cfg, datetime(2026, 9, 13, 23, 30))
    assert not in_quiet_hours(cfg, datetime(2026, 9, 13, 12, 0))
    cfg2 = AppConfig(targets=[T], notifiers=[], schedule=ScheduleConfig(quiet_hours=["09:00-10:00"]))
    assert in_quiet_hours(cfg2, datetime(2026, 9, 13, 9, 30))
    assert not in_quiet_hours(cfg2, datetime(2026, 9, 13, 10, 0))


def test_format_opened():
    title, body, url = format_opened(T, [_slot("2026-09-19", "2회차 11:00~12:50", SlotStatus.OPEN, 3)])
    assert "1건" in title and "2026-09-19(토)" in body and "잔여 3" in body and "YF" not in url
