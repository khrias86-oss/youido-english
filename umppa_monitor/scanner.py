"""수집 결과(FetchResult) -> Slot 목록 변환 및 필터.

파서 우선순위:
  1. 날짜 클릭으로 얻은 회차 목록 HTML (가장 구체적)
  2. XHR JSON 응답
  3. 달력/상세 페이지 DOM
같은 (날짜, 회차) 키가 여러 소스에서 나오면 더 구체적인 소스가 이긴다.
"""

from __future__ import annotations

import logging

from .browser import FetchResult
from .config import ParserOverrides
from .models import Slot, SlotStatus, Target, TargetKind
from .parsers.calendar import parse_calendar_html, parse_slot_list_html
from .parsers.network import parse_json_payload
from .parsers.program import parse_program_html

log = logging.getLogger(__name__)


def slots_from_result(result: FetchResult, overrides: ParserOverrides) -> list[Slot]:
    target = result.target
    merged: dict[str, Slot] = {}

    def put(slots: list[Slot], source: str) -> None:
        for s in slots:
            if s.status == SlotStatus.UNKNOWN and s.key in merged:
                continue
            # 날짜 단위(day) 슬롯은 같은 날짜의 회차 단위 슬롯이 있으면 버린다
            merged[s.key] = s
        log.debug("%s: %d slots from %s", target.key, len(slots), source)

    if target.kind == TargetKind.PROGRAM:
        for url, html in result.pages:
            put(parse_program_html(html, target, overrides, url), "program-page")
        for r in result.network:
            if r.json_obj is not None:
                put(parse_json_payload(r.json_obj, target, r.url), "xhr")
    else:
        for url, html in result.pages:
            put(parse_calendar_html(html, target, overrides, url), "calendar-page")
        for r in result.network:
            if r.json_obj is not None:
                put(parse_json_payload(r.json_obj, target, r.url), "xhr")
        for d, url, html in result.slot_pages:
            put(parse_slot_list_html(html, target, d, overrides, url), "slot-page")

    slots = list(merged.values())
    # 회차 단위가 있는 날짜의 'day' 슬롯 제거
    dates_with_sessions = {s.date for s in slots if s.session != "day" and s.date}
    slots = [s for s in slots if not (s.session == "day" and s.date in dates_with_sessions)]
    # 날짜/회차 없는 잡음 제거 (프로그램은 날짜가 없어도 허용)
    if target.kind == TargetKind.KIDSCAFE:
        slots = [s for s in slots if s.date]
    slots.sort(key=lambda s: (s.date or "", s.session))
    return slots


def apply_filters(slots: list[Slot], target: Target) -> list[Slot]:
    out: list[Slot] = []
    for s in slots:
        if target.dates and (s.date not in target.dates):
            continue
        if target.weekdays:
            wd = s.weekday()
            if wd is None or wd not in target.weekdays:
                continue
        if target.sessions and not any(k in s.session or k in s.raw for k in target.sessions):
            continue
        out.append(s)
    return out


def is_notifiable(slot: Slot, target: Target) -> bool:
    if not slot.is_open:
        return False
    if slot.remaining is not None and slot.remaining < target.min_remaining:
        return False
    return True
