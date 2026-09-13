"""AJAX(JSON) 응답 파서.

달력/회차 정보를 XHR 로 받아오는 경우, 브라우저가 가로챈 JSON 을 일반적인
키 이름 패턴으로 해석한다. 키 이름은 공공기관 Java 표준 약어(resveDe,
psncpa, nmpr, rmndr ...)를 포함해 넓게 매칭한다.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..models import Slot, SlotStatus, Target, normalize_date
from .common import extract_session_label

DATE_KEY_RE = re.compile(r"(de|dt|date|ymd|day|dy)$", re.I)
REMAIN_KEY_RE = re.compile(r"(rmndr|remain|rest|resid|vacan|jan|avail|possbl|able)", re.I)
CAPACITY_KEY_RE = re.compile(r"(psncpa|capa|capacity|defn|jungwon|totnmpr|tot_nmpr|maxnmpr|max_nmpr|limit|recrut)", re.I)
RESERVED_KEY_RE = re.compile(r"(resvenmpr|resve_nmpr|resvecnt|resve_cnt|reqstnmpr|reqst_cnt|reqstcnt|aplcnt|apply|reserved|booked|useNmpr|cnt$)", re.I)
STATUS_KEY_RE = re.compile(r"(stts|status|state|yn$|at$|posbl|possible|able)", re.I)
TIME_KEY_RE = re.compile(r"(time|tm|hr|hour|begin|end|bgn|strt)", re.I)
SESSION_KEY_RE = re.compile(r"(rnd|round|tme|turn|seq|ordr|sn$|no$|nm$|name)", re.I)


def _walk(obj: Any) -> Iterable[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _fmt_time(v: str) -> str:
    d = re.sub(r"\D", "", v)
    if len(d) == 3:
        d = "0" + d
    return f"{d[:2]}:{d[2:4]}" if len(d) >= 4 else v.strip()


def _to_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*-?\d+\s*", v):
        return int(v)
    return None


def _record_to_slot(rec: dict, target: Target, url: str) -> Slot | None:
    date_val: str | None = None
    remaining: int | None = None
    capacity: int | None = None
    reserved: int | None = None
    status_hint: str | None = None
    time_parts: list[str] = []
    session_parts: list[str] = []

    for k, v in rec.items():
        if isinstance(v, (dict, list)):
            continue
        ks = str(k)
        if date_val is None and DATE_KEY_RE.search(ks) and isinstance(v, str):
            date_val = normalize_date(v)
            if date_val:
                continue
        if isinstance(v, str) and TIME_KEY_RE.search(ks) and re.fullmatch(r"\s*\d{1,2}:?\d{2}\s*", v):
            time_parts.append(_fmt_time(v))
            continue
        iv = _to_int(v)
        if iv is not None:
            if REMAIN_KEY_RE.search(ks) and remaining is None:
                remaining = iv
            elif CAPACITY_KEY_RE.search(ks) and capacity is None:
                capacity = iv
            elif RESERVED_KEY_RE.search(ks) and reserved is None:
                reserved = iv
        elif isinstance(v, str) and STATUS_KEY_RE.search(ks):
            status_hint = v
        if isinstance(v, str) and SESSION_KEY_RE.search(ks) and len(v) <= 40 and not DATE_KEY_RE.search(ks):
            session_parts.append(v)

    if date_val is None and remaining is None and capacity is None:
        return None
    if remaining is None and capacity is not None and reserved is not None:
        remaining = max(capacity - reserved, 0)

    if remaining is not None:
        status = SlotStatus.OPEN if remaining > 0 else SlotStatus.FULL
    elif status_hint is not None:
        h = status_hint.upper()
        if h in ("Y", "TRUE", "1", "OPEN", "POSSIBLE", "가능", "예약가능"):
            status = SlotStatus.OPEN
        elif h in ("N", "FALSE", "0", "CLOSE", "CLOSED", "마감", "불가"):
            status = SlotStatus.FULL if "마감" in status_hint else SlotStatus.CLOSED
        else:
            status = SlotStatus.UNKNOWN
    else:
        return None

    if len(time_parts) >= 2:
        time_label = f"{time_parts[0]}~{time_parts[1]}"
    else:
        time_label = " ".join(time_parts)
    label_src = " ".join(session_parts + [time_label])
    session = extract_session_label(label_src) if label_src else "day"
    raw = ", ".join(f"{k}={v}" for k, v in rec.items() if not isinstance(v, (dict, list)))[:300]
    return Slot(target.key, target.kind, date_val, session or "day", status, remaining, capacity, raw, url)


def parse_json_payload(obj: Any, target: Target, url: str = "") -> list[Slot]:
    slots: list[Slot] = []
    seen: set[str] = set()
    for rec in _walk(obj):
        s = _record_to_slot(rec, target, url)
        if s and s.key not in seen:
            seen.add(s.key)
            slots.append(s)
    return slots
