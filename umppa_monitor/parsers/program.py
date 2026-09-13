"""키즈카페 프로그램 페이지 파서.

대상: BD_selectKidsCafeProgrm.do?q_progrmSn=NNNN (상세) 또는
BD_selectKidsCafeProgrmList.do (목록). 상세 페이지에는 보통 프로그램명,
운영일시, 정원/모집인원, 신청인원, 접수기간, 신청 버튼(신청하기/마감)이 있다.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..config import ParserOverrides
from ..models import Slot, SlotStatus, Target, normalize_date
from .common import (
    classify_text, extract_numbers, extract_session_label, normalize_ws, table_row_numbers,
    SESSION_RE, TIME_RANGE_RE,
)

TITLE_HINTS = ("프로그램명", "프로그램 명", "제목", "명칭")
DATE_HINTS = ("운영일", "운영 일", "일시", "일자", "교육일", "진행일", "프로그램일")


def _kv_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """th/td 또는 dt/dd 쌍을 dict 로."""
    pairs: dict[str, str] = {}
    for th in soup.find_all("th"):
        td = th.find_next_sibling("td")
        if td is not None:
            pairs[normalize_ws(th.get_text(" "))] = normalize_ws(td.get_text(" "))
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            pairs[normalize_ws(dt.get_text(" "))] = normalize_ws(dd.get_text(" "))
    return pairs


def _lookup(pairs: dict[str, str], hints: tuple[str, ...]) -> str | None:
    for k, v in pairs.items():
        if any(h in k for h in hints):
            return v
    return None


def _program_title(soup: BeautifulSoup, pairs: dict[str, str]) -> str:
    t = _lookup(pairs, TITLE_HINTS)
    if t:
        return t
    for sel in ("h2", "h3", "h4", ".tit", ".title", "[class*=tit]", "strong"):
        el = soup.select_one(sel)
        if el:
            txt = normalize_ws(el.get_text(" "))
            if 2 <= len(txt) <= 80 and "HOME" not in txt:
                return txt
    return "프로그램"


def _action_state(soup: BeautifulSoup) -> tuple[bool | None, str]:
    """신청 버튼 상태로 열림/닫힘 판단. (clickable, text)"""
    for el in soup.find_all(["button", "a", "input"]):
        txt = normalize_ws(el.get_text(" ")) or normalize_ws(str(el.get("value") or ""))
        if not txt:
            continue
        if any(k in txt for k in ("신청", "예약", "접수", "마감")):
            disabled = el.has_attr("disabled") or "disabled" in " ".join(el.get("class", []) or [])
            if any(k in txt for k in ("마감", "종료", "불가")):
                return False, txt
            if any(k in txt for k in ("신청하기", "예약하기", "접수하기", "신청", "예약")):
                return (not disabled), txt
    return None, ""


def parse_program_html(
    html: str,
    target: Target,
    overrides: ParserOverrides | None = None,
    page_url: str = "",
) -> list[Slot]:
    ov = overrides or ParserOverrides()
    soup = BeautifulSoup(html, "lxml")
    pairs = _kv_pairs(soup)
    title = _program_title(soup, pairs)
    body_text = normalize_ws(soup.get_text(" "))

    # 1) 회차별 행(테이블)이 있으면 회차 단위로
    rows: list[Tag] = [
        tr for tr in soup.find_all("tr")
        if (SESSION_RE.search(tr.get_text(" ")) or TIME_RANGE_RE.search(tr.get_text(" ")) or normalize_date(tr.get_text(" ")))
        and tr.find("th") is None
        and len(normalize_ws(tr.get_text(" "))) < 300
    ]
    slots: list[Slot] = []
    if rows:
        seen: set[str] = set()
        for tr in rows:
            et = normalize_ws(tr.get_text(" "))
            inputs = tr.find_all(["input", "button", "a"])
            disabled = any(i.has_attr("disabled") for i in inputs)
            clickable: bool | None = (not disabled) if inputs else None
            r_hdr, c_hdr = table_row_numbers(tr)
            cl = classify_text(et, ov.open_keywords, ov.closed_keywords, ov.remaining_regex, clickable=clickable,
                               remaining=r_hdr, capacity=c_hdr)
            if disabled and cl.remaining is None and cl.status == SlotStatus.OPEN:
                cl.status = SlotStatus.FULL
            d = normalize_date(et)
            label = f"{title} {extract_session_label(et)}".strip()
            s = Slot(target.key, target.kind, d, label, cl.status, cl.remaining, cl.capacity, et, page_url)
            if s.key not in seen:
                seen.add(s.key)
                slots.append(s)
        return slots

    # 2) 단일 프로그램: 정원/신청인원 + 버튼 상태
    cap_text = " ".join(
        f"{k} {v}" for k, v in pairs.items()
        if any(h in k for h in ("정원", "모집", "인원", "신청", "접수", "잔여", "상태"))
    ) or body_text
    remaining, capacity = extract_numbers(cap_text, ov.remaining_regex)
    clickable, btn_text = _action_state(soup)
    status_text = " ".join(filter(None, [cap_text, btn_text, _lookup(pairs, ("상태", "접수상태", "신청상태")) or ""]))
    cl = classify_text(status_text, ov.open_keywords, ov.closed_keywords, ov.remaining_regex, clickable=clickable)
    if cl.remaining is None and remaining is not None:
        cl.remaining = remaining
    if cl.capacity is None and capacity is not None:
        cl.capacity = capacity
    # 잔여가 0인데 버튼 텍스트만으로 OPEN 이 되었다면 FULL 로 보정
    if cl.remaining == 0:
        cl.status = SlotStatus.FULL
    when = _lookup(pairs, DATE_HINTS) or ""
    d = normalize_date(when) or normalize_date(body_text)
    label = title if not when else f"{title} {extract_session_label(when)}".strip()
    return [Slot(target.key, target.kind, d, label, cl.status, cl.remaining, cl.capacity,
                 normalize_ws(status_text)[:300], page_url)]
