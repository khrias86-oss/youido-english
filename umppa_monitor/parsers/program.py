"""키즈카페 프로그램 페이지 파서.

대상: BD_selectKidsCafeProgrm.do?q_progrmSn=NNNN (상세) 또는
BD_selectKidsCafeProgrmList.do (목록). 상세 페이지에는 보통 프로그램명,
운영일시, 정원/모집인원, 신청인원, 접수기간, 신청 버튼(신청하기/마감)이 있다.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..config import ParserOverrides
from ..models import BASE_URL, PROGRAM_VIEW_PATH, Slot, SlotStatus, Target, normalize_date
from .common import (
    classify_text, extract_numbers, extract_session_label, normalize_ws, table_row_numbers,
    SESSION_RE, TIME_RANGE_RE,
)

TITLE_HINTS = ("프로그램명", "프로그램 명", "제목", "명칭")
DATE_HINTS = ("운영일", "운영 일", "일시", "일자", "교육일", "진행일", "프로그램일")

# 목록 페이지에서 프로그램 번호를 뽑는 패턴.
# href="...q_progrmSn=8644", onclick="fn_view('8644')" 같은 표기를 모두 잡는다.
PROGRM_SN_RE = re.compile(r"progrm_?sn['\"]?\s*[=:,(]\s*['\"]?(\d{1,10})", re.I)
# 번호를 파라미터 이름 없이 함수 인자로만 넘기는 표기 (onclick="fn_view('8644')").
# 목록 페이지에서만 쓰이고 결과는 사용자가 골라야 하므로, 다소 느슨해도 위험이 낮다.
CALL_SN_RE = re.compile(r"\b\w*(?:progrm|view|detail|resve)\w*\s*\(\s*['\"]?(\d{3,10})", re.I)
PERIOD_RE = re.compile(r"20\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}")
LIST_STATUS_HINTS = ("접수중", "접수 중", "신청가능", "마감", "접수마감", "대기", "종료", "예정")


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


def _list_row_name(el: Tag, raw: str) -> str:
    """목록 행에서 프로그램 이름만 뽑는다. 보통 제목이 링크 텍스트다."""
    cands = ([el] if el.name in ("a", "button") else []) + el.find_all(["a", "button"], limit=6)
    for a in cands:
        t = normalize_ws(a.get_text(" "))
        if 2 <= len(t) <= 80 and not t.replace(" ", "").isdigit() \
                and not any(k in t for k in ("자세히", "상세", "더보기", "보기", "신청하기", "목록")):
            return t
    # 링크 텍스트가 없으면 행 텍스트에서 기간·숫자·상태어를 걷어낸다
    t = PERIOD_RE.sub(" ", raw)
    for k in LIST_STATUS_HINTS:
        t = t.replace(k, " ")
    t = normalize_ws(re.sub(r"[\d/~\-·|()]+", " ", t))
    return t[:60] or "프로그램"


def parse_program_list_html(html: str, page_url: str = "") -> list[dict]:
    """프로그램 목록 페이지에서 선택 가능한 프로그램들을 뽑는다.

    웹 앱이 "어떤 프로그램을 감시할지" 고르게 하려면 번호(q_progrmSn)와 이름이
    필요하다. 같은 번호가 여러 요소에서 잡히면 정보가 가장 많은 행을 남긴다.
    """
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, dict] = {}
    for el in soup.find_all(["tr", "li", "a", "button", "div"]):
        attr_text = " ".join(
            str(el.get(a) or "") for a in ("href", "onclick", "value", "id", "data-sn", "data-progrm-sn"))
        texts = [attr_text] + [
            " ".join(str(child.get(a) or "") for a in ("href", "onclick", "value", "id"))
            for child in el.find_all(["a", "button", "input"], limit=6)
        ]
        m = next((mm for t in texts if (mm := PROGRM_SN_RE.search(t))), None) \
            or next((mm for t in texts if (mm := CALL_SN_RE.search(t))), None)
        if not m:
            continue
        raw = normalize_ws(el.get_text(" "))
        if not raw or len(raw) > 400:
            continue
        sn = m.group(1)
        # 같은 번호가 여러 요소에서 잡힌다. 행(tr/li)이 기간·상태까지 품고 있어 가장 좋고,
        # 같은 등급이면 더 짧은 쪽이 목록 전체를 감싼 컨테이너가 아닐 가능성이 높다.
        rank = {"tr": 2, "li": 2, "a": 1, "button": 1}.get(el.name, 0)
        prev = found.get(sn)
        if prev is not None and (prev["_rank"], -len(prev["raw"])) >= (rank, -len(raw)):
            continue
        status = next((k for k in LIST_STATUS_HINTS if k in raw), "")
        periods = PERIOD_RE.findall(raw)
        found[sn] = {
            "id": sn,
            "name": _list_row_name(el, raw),
            "status": status,
            "period": " ~ ".join(periods[:2]) if periods else "",
            "url": f"{BASE_URL}{PROGRAM_VIEW_PATH}?q_progrmSn={sn}",
            "raw": raw[:200],
            "_rank": rank,
        }
    out = sorted(found.values(), key=lambda p: int(p["id"]))
    for p in out:
        p.pop("_rank", None)
    return out


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
