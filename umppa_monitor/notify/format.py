"""알림 메시지 포맷."""

from __future__ import annotations

from datetime import date as _date

from ..models import Slot, Target

WEEKDAY_KO = "월화수목금토일"


def _fmt_date(d: str | None) -> str:
    if not d:
        return "날짜 미상"
    try:
        y, m, dd = (int(x) for x in d.split("-"))
        return f"{d}({WEEKDAY_KO[_date(y, m, dd).weekday()]})"
    except ValueError:
        return d


def format_slot_line(s: Slot) -> str:
    parts = [_fmt_date(s.date), s.session if s.session != "day" else "(회차 미상)"]
    if s.remaining is not None:
        cap = f"/{s.capacity}" if s.capacity is not None else ""
        parts.append(f"잔여 {s.remaining}{cap}")
    return " · ".join(parts)


def format_opened(target: Target, slots: list[Slot]) -> tuple[str, str, str]:
    title = f"[빈자리] {target.display_name()} - {len(slots)}건 예약 가능"
    lines = [format_slot_line(s) for s in slots[:30]]
    if len(slots) > 30:
        lines.append(f"... 외 {len(slots) - 30}건")
    body = "\n".join(lines)
    return title, body, target.resolved_url()


def format_closed(target: Target, slots: list[Slot]) -> tuple[str, str, str]:
    title = f"[마감] {target.display_name()} - {len(slots)}건 닫힘"
    body = "\n".join(format_slot_line(s) for s in slots[:30])
    return title, body, target.resolved_url()
