from pathlib import Path

from umppa_monitor.config import ParserOverrides
from umppa_monitor.models import SlotStatus, Target, TargetKind
from umppa_monitor.parsers.calendar import parse_calendar_html, parse_slot_list_html, find_year_month
from umppa_monitor.parsers.common import classify_text, extract_numbers, extract_session_label
from umppa_monitor.parsers.network import parse_json_payload
from umppa_monitor.parsers.program import parse_program_html
from bs4 import BeautifulSoup

FX = Path(__file__).parent / "fixtures"
KC = Target(kind=TargetKind.KIDSCAFE, id="YF260101", name="테스트")
PG = Target(kind=TargetKind.PROGRAM, id="8644", name="프로그램")


def _fx(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def test_extract_numbers_variants():
    assert extract_numbers("잔여 3") == (3, None)
    assert extract_numbers("잔여: 0명") == (0, None)
    assert extract_numbers("예약 3/20") == (17, 20)
    assert extract_numbers("잔여 3 / 20") == (3, 20)
    assert extract_numbers("정원 20명 신청인원 12명") == (8, 20)
    assert extract_numbers("남은 인원 4") == (4, None)
    assert extract_numbers("5명 남음") == (5, None)
    assert extract_numbers("예약가능") == (None, None)


def test_classify_keywords():
    assert classify_text("예약가능").status == SlotStatus.OPEN
    assert classify_text("예약마감").status == SlotStatus.FULL
    assert classify_text("휴관").status == SlotStatus.CLOSED
    assert classify_text("예약불가").status == SlotStatus.CLOSED
    # 숫자가 키워드보다 우선
    assert classify_text("예약가능 잔여 0").status == SlotStatus.FULL
    assert classify_text("마감 임박 잔여 1").status == SlotStatus.OPEN
    # 클릭 가능 여부 fallback
    assert classify_text("12", clickable=True).status == SlotStatus.OPEN
    assert classify_text("12", clickable=False).status == SlotStatus.CLOSED
    assert classify_text("12").status == SlotStatus.UNKNOWN
    # 사용자 키워드 우선
    assert classify_text("접수가능", open_keywords=["접수가능"]).status == SlotStatus.OPEN


def test_session_label():
    assert extract_session_label("1회차 10:00~12:00 잔여 2") == "1회차 10:00~12:00"
    assert extract_session_label("2 회차 13:30 ~ 15:30") == "2회차 13:30~15:30"
    assert extract_session_label("14:00 시작") == "14:00"


def test_find_year_month():
    soup = BeautifulSoup(_fx("calendar_table.html"), "lxml")
    assert find_year_month(soup) == (2026, 9)


def test_parse_calendar_table():
    slots = parse_calendar_html(_fx("calendar_table.html"), KC, ParserOverrides(), "u")
    by = {(s.date, s.session): s for s in slots}
    # 다른 달 셀 제외
    assert all(s.date.startswith("2026-09") for s in slots)
    assert by[("2026-09-01", "day")].status == SlotStatus.CLOSED
    assert by[("2026-09-02", "day")].status == SlotStatus.FULL
    assert by[("2026-09-03", "day")].status == SlotStatus.OPEN
    # 셀 안 회차 단위
    assert by[("2026-09-04", "1회차 10:00~12:00")].status == SlotStatus.FULL
    s = by[("2026-09-04", "2회차 13:30~15:30")]
    assert s.status == SlotStatus.OPEN and s.remaining == 2
    s = by[("2026-09-05", "1회차 09:00~10:50")]
    assert s.status == SlotStatus.OPEN and s.remaining == 17 and s.capacity == 20
    assert by[("2026-09-05", "2회차 11:00~12:50")].status == SlotStatus.FULL
    assert by[("2026-09-06", "day")].status == SlotStatus.CLOSED
    assert by[("2026-09-07", "day")].status == SlotStatus.CLOSED   # 클릭 요소 없음
    assert by[("2026-09-08", "day")].status == SlotStatus.OPEN     # data-date
    s = by[("2026-09-09", "day")]
    assert s.status == SlotStatus.OPEN and s.remaining == 5
    assert by[("2026-09-10", "day")].status == SlotStatus.FULL


def test_parse_calendar_with_selector_override():
    ov = ParserOverrides(calendar_cell_selector="table.calendar td", date_attr="data-date")
    slots = parse_calendar_html(_fx("calendar_table.html"), KC, ov, "u")
    assert any(s.date == "2026-09-08" and s.status == SlotStatus.OPEN for s in slots)


def test_parse_slot_list_table():
    slots = parse_slot_list_html(_fx("slot_list.html"), KC, "2026-09-20", ParserOverrides(), "u")
    by = {s.session: s for s in slots}
    assert set(by) >= {"1회차 09:00~10:50", "2회차 11:00~12:50", "3회차 14:00~15:50", "4회차 16:00~17:50"}
    assert by["1회차 09:00~10:50"].status == SlotStatus.FULL
    s = by["2회차 11:00~12:50"]
    assert s.status == SlotStatus.OPEN and s.remaining == 2 and s.capacity == 20
    assert by["3회차 14:00~15:50"].status == SlotStatus.FULL
    s = by["4회차 16:00~17:50"]
    assert s.status == SlotStatus.OPEN and s.remaining == 7
    assert all(s.date == "2026-09-20" for s in slots)


def test_parse_slot_list_buttons():
    slots = parse_slot_list_html(_fx("slot_list_buttons.html"), KC, "2026-09-21", ParserOverrides(), "u")
    by = {s.session: s for s in slots}
    assert by["1회차 10:00~12:00"].status == SlotStatus.FULL
    assert by["2회차 13:30~15:30"].status == SlotStatus.OPEN
    s = by["3회차 16:00~18:00"]
    assert s.status == SlotStatus.OPEN and s.remaining == 4


def test_parse_program_full():
    slots = parse_program_html(_fx("program_detail.html"), PG, ParserOverrides(), "u")
    assert len(slots) == 1
    s = slots[0]
    assert s.status == SlotStatus.FULL
    assert s.remaining == 0 and s.capacity == 12
    assert s.date == "2026-10-03"
    assert "가을 숲속 공예교실" in s.session


def test_parse_program_open():
    slots = parse_program_html(_fx("program_detail_open.html"), PG, ParserOverrides(), "u")
    s = slots[0]
    assert s.status == SlotStatus.OPEN
    assert s.remaining == 6 and s.capacity == 15
    assert s.date == "2026-10-09"
    assert "한글날 그림책 놀이" in s.session


def test_parse_program_rounds():
    slots = parse_program_html(_fx("program_rounds.html"), PG, ParserOverrides(), "u")
    assert len(slots) == 2
    by = {s.session: s for s in slots}
    k1 = next(k for k in by if "1회차" in k)
    k2 = next(k for k in by if "2회차" in k)
    assert by[k1].status == SlotStatus.FULL
    assert by[k2].status == SlotStatus.OPEN and by[k2].remaining == 4
    assert by[k2].date == "2026-10-10"


def test_parse_json_payload_variants():
    payload = {
        "result": "OK",
        "list": [
            {"resveDe": "20260920", "tmeSe": "1", "bgnTm": "0900", "endTm": "1050", "psncpa": 20, "resveNmpr": 20},
            {"resveDe": "20260920", "tmeSe": "2", "bgnTm": "1100", "endTm": "1250", "psncpa": 20, "resveNmpr": 15},
            {"resveDe": "20260921", "rmndrNmpr": "3", "tmeNm": "3회차"},
            {"resveDe": "20260922", "resvePosblAt": "N"},
            {"resveDe": "20260923", "resvePosblAt": "Y"},
        ],
    }
    slots = parse_json_payload(payload, KC, "xhr")
    by = {(s.date, s.session): s for s in slots}
    assert len(slots) == 5
    full = [s for s in slots if s.date == "2026-09-20" and s.status == SlotStatus.FULL]
    opn = [s for s in slots if s.date == "2026-09-20" and s.status == SlotStatus.OPEN]
    assert len(full) == 1 and len(opn) == 1 and opn[0].remaining == 5
    assert by[("2026-09-21", "3회차")].remaining == 3
    assert by[("2026-09-22", "day")].status == SlotStatus.CLOSED
    assert by[("2026-09-23", "day")].status == SlotStatus.OPEN
