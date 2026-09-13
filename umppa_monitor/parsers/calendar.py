"""키즈카페 달력(BD_selectKidsCafeResveCal.do) 및 회차 목록 파서 (DOM 휴리스틱)."""

from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ..config import ParserOverrides
from ..models import Slot, SlotStatus, Target, normalize_date
from .common import (classify_text, extract_round_counts, extract_session_label, normalize_ws,
                     table_row_numbers, TIME_RANGE_RE, SESSION_RE)

DAY_NUM_RE = re.compile(r"^\s*(\d{1,2})\s*(?:일)?\s*$")
YEAR_MONTH_RE = re.compile(r"(20\d{2})\s*[.년\-/]\s*(\d{1,2})\s*(?:월)?")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def find_year_month(soup: BeautifulSoup) -> tuple[int, int] | None:
    """달력 헤더에서 연/월을 찾는다 ('2026.09', '2026년 9월', input[name=q_...Ym] 등)."""
    for inp in soup.select("input[type=hidden], input"):
        name = (inp.get("name") or inp.get("id") or "").lower()
        val = inp.get("value") or ""
        if any(k in name for k in ("ym", "month", "yearmonth", "srchym", "q_resveym")):
            m = re.match(r"^(20\d{2})[-./]?(\d{1,2})", val)
            if m:
                return int(m.group(1)), int(m.group(2))
    for el in soup.select("[class*=month], [class*=cal], [id*=month], [id*=cal], h2, h3, h4, strong, span, p, div"):
        txt = normalize_ws(el.get_text(" "))
        if len(txt) > 60:
            continue
        m = YEAR_MONTH_RE.search(txt)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _cell_date(cell: Tag, year: int | None, month: int | None, date_attr: str | None) -> str | None:
    # 1) 속성 기반
    attrs_to_try = [date_attr] if date_attr else []
    attrs_to_try += ["data-date", "data-ymd", "data-day", "data-dt", "data-resve-de", "id", "title"]
    for a in attrs_to_try:
        if not a:
            continue
        v = cell.get(a)
        if v:
            d = normalize_date(str(v))
            if d:
                return d
    for desc in cell.find_all(True):
        for a in ["data-date", "data-ymd", "data-day", "data-dt", "onclick", "href", "title"]:
            v = desc.get(a)
            if v:
                d = normalize_date(str(v))
                if d:
                    return d
    onclick = cell.get("onclick")
    if onclick:
        d = normalize_date(str(onclick))
        if d:
            return d
    # 2) 일(day) 숫자 + 헤더 연/월
    if year and month:
        for cand in [cell.find(["em", "strong", "span", "a", "button", "b", "p"]), cell]:
            if cand is None:
                continue
            txt = normalize_ws(cand.get_text(" "))
            m = DAY_NUM_RE.match(txt) or re.match(r"^\s*(\d{1,2})\b", txt)
            if m:
                day = int(m.group(1))
                if 1 <= day <= 31:
                    return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _is_other_month(cell: Tag) -> bool:
    cls = " ".join(cell.get("class", []) or [])
    return any(k in cls for k in ("other", "prev", "next", "disabled-month", "noday", "empty", "blank"))


def _is_clickable(cell: Tag) -> bool:
    if cell.find(["a", "button"]) is not None:
        return True
    if cell.get("onclick"):
        return True
    return False


def _candidate_cells(soup: BeautifulSoup, selector: str | None) -> list[Tag]:
    if selector:
        return list(soup.select(selector))
    # 달력으로 보이는 table 찾기: 요일 헤더(일 월 화 ...)가 있는 table 우선
    tables = soup.find_all("table")
    best: list[Tag] = []
    for t in tables:
        head = normalize_ws(t.get_text(" "))[:200]
        if sum(1 for d in ("일", "월", "화", "수", "목", "금", "토") if d in head) >= 5:
            best = t.select("td")
            if best:
                return best
    if tables:
        cells = [td for t in tables for td in t.select("td")]
        if cells:
            return cells
    # table 이 아닌 div 기반 달력
    return list(soup.select("[class*=day], [class*=date], li[data-date], div[data-date]"))


def parse_calendar_html(
    html: str,
    target: Target,
    overrides: ParserOverrides | None = None,
    page_url: str = "",
) -> list[Slot]:
    """달력 페이지에서 날짜 단위(및 셀 안의 회차 단위) Slot 추출.

    셀 안에 회차별 정보가 있으면 회차 단위 Slot 을, 없으면 날짜 단위 Slot(session='day') 을 만든다.
    """
    ov = overrides or ParserOverrides()
    soup = _soup(html)
    ym = find_year_month(soup)
    year, month = (ym if ym else (None, None))
    slots: list[Slot] = []
    seen: set[str] = set()

    for cell in _candidate_cells(soup, ov.calendar_cell_selector):
        if _is_other_month(cell):
            continue
        d = _cell_date(cell, year, month, ov.date_attr)
        if not d:
            continue
        text = normalize_ws(cell.get_text(" "))
        # 셀 안에 여러 회차가 개별 요소로 있는 경우
        sub_items = [
            el for el in cell.find_all(["li", "a", "button", "p", "span", "div"])
            if (SESSION_RE.search(el.get_text(" ")) or TIME_RANGE_RE.search(el.get_text(" ")))
        ]
        # 중첩된 요소 제거 (부모가 이미 후보면 자식 제외)
        leaf_items = [el for el in sub_items if not any(p in sub_items for p in el.parents)]
        if leaf_items:
            for el in leaf_items:
                et = normalize_ws(el.get_text(" "))
                cl = classify_text(et, ov.open_keywords, ov.closed_keywords, ov.remaining_regex,
                                   clickable=(el.name in ("a", "button") or el.find(["a", "button"]) is not None))
                slot = Slot(target.key, target.kind, d, extract_session_label(et), cl.status,
                            cl.remaining, cl.capacity, et, page_url)
                if slot.key not in seen:
                    seen.add(slot.key)
                    slots.append(slot)
            continue

        day_text = re.sub(r"^\s*\d{1,2}\s*(일)?\s*", "", text)  # 앞의 일자 숫자 제거

        # 우리동네키움포털 실사이트 표기: "1회 개인 0 2회 개인 0 3회 개인 2 ..." 처럼
        # 회차별 잔여 인원이 별도 하위 요소 없이 한 셀 텍스트에 나열되는 경우가 있다.
        # (SESSION_RE 의 "N회차" 표기와 달리 "N회"+구분+숫자 형태라 leaf_items 로는 안 잡힘)
        rounds = extract_round_counts(day_text)
        if rounds:
            for rnd, kind, remaining in rounds:
                status = SlotStatus.OPEN if remaining > 0 else SlotStatus.FULL
                label = f"{rnd}회차" + (f" {kind}" if kind else "")
                slot = Slot(target.key, target.kind, d, label, status, remaining, None, day_text, page_url)
                if slot.key not in seen:
                    seen.add(slot.key)
                    slots.append(slot)
            continue

        cl = classify_text(day_text, ov.open_keywords, ov.closed_keywords, ov.remaining_regex,
                           clickable=_is_clickable(cell))
        slot = Slot(target.key, target.kind, d, "day", cl.status, cl.remaining, cl.capacity, text, page_url)
        if slot.key not in seen:
            seen.add(slot.key)
            slots.append(slot)
    return slots


def parse_slot_list_html(
    html: str,
    target: Target,
    date: str | None,
    overrides: ParserOverrides | None = None,
    page_url: str = "",
) -> list[Slot]:
    """날짜 클릭 후 나타나는 회차 목록(모달/영역/페이지)에서 회차 단위 Slot 추출."""
    ov = overrides or ParserOverrides()
    soup = _soup(html)
    slots: list[Slot] = []
    seen: set[str] = set()

    if ov.slot_selector:
        items: Iterable[Tag] = soup.select(ov.slot_selector)
    else:
        # 회차/시간 문구가 있는 최소 단위 요소들
        cands = [
            el for el in soup.find_all(["tr", "li", "label", "a", "button", "p", "div", "span", "td"])
            if (SESSION_RE.search(el.get_text(" ")) or TIME_RANGE_RE.search(el.get_text(" ")))
            and len(normalize_ws(el.get_text(" "))) < 200
        ]
        # 가장 안쪽(leaf) 후보만, 단 tr/li 는 행 전체를 대표하므로 우선
        rows = [el for el in cands if el.name in ("tr", "li", "label")]
        rows = [el for el in rows if not any(p in rows for p in el.parents)]
        if rows:
            items = rows
        else:
            items = [el for el in cands if not any(p in cands for p in el.parents)]

    for el in items:
        et = normalize_ws(el.get_text(" "))
        if not et:
            continue
        inputs = el.find_all("input")
        disabled = any(i.has_attr("disabled") for i in inputs) or el.has_attr("disabled")
        clickable: bool | None = None
        if el.name in ("a", "button") or el.find(["a", "button"]) is not None or inputs:
            clickable = not disabled
        r_hdr, c_hdr = table_row_numbers(el) if el.name == "tr" else (None, None)
        cl = classify_text(et, ov.open_keywords, ov.closed_keywords, ov.remaining_regex, clickable=clickable,
                           remaining=r_hdr, capacity=c_hdr)
        if disabled and cl.remaining is None and cl.status in (SlotStatus.OPEN, SlotStatus.CLOSED) and cl.reason in ("not-clickable", "clickable") or (
            disabled and cl.reason.startswith("keyword:") and cl.status == SlotStatus.OPEN
        ):
            # 선택 불가(disabled)인 회차는 존재하되 고를 수 없는 상태 -> 마감으로 본다
            cl.status = SlotStatus.FULL
        slot_date = date
        if not slot_date:
            slot_date = normalize_date(et) or normalize_date(str(el.get("data-date") or ""))
        slot = Slot(target.key, target.kind, slot_date, extract_session_label(et), cl.status,
                    cl.remaining, cl.capacity, et, page_url)
        if slot.key not in seen:
            seen.add(slot.key)
            slots.append(slot)
    return slots
