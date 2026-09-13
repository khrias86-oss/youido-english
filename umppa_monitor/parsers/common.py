"""파서 공통 휴리스틱.

사이트의 실제 마크업을 사전에 확정할 수 없으므로, 한국 공공 예약 시스템에서
흔히 쓰이는 문구/패턴을 넓게 포괄하는 휴리스틱으로 상태를 판별한다.
`inspect` 명령으로 실제 구조를 확인한 뒤 config.parser 로 정밀화할 수 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import SlotStatus

# 열림(예약 가능)을 뜻하는 문구
OPEN_KEYWORDS = [
    "예약가능", "예약 가능", "신청가능", "신청 가능", "접수중", "접수 중",
    "예약하기", "신청하기", "예약신청", "신청", "가능",
]
# 닫힘(마감/불가)을 뜻하는 문구. 열림 문구보다 우선한다.
CLOSED_KEYWORDS = [
    "예약마감", "예약 마감", "정원마감", "마감", "예약불가", "예약 불가",
    "신청불가", "불가", "휴관", "휴무", "운영안함", "운영 안함", "종료",
    "대기", "만석", "예약완료", "접수마감", "접수 마감", "매진",
]
# 아직 열리지 않았거나 대상 외 (판별 시 closed 로 취급)
INACTIVE_KEYWORDS = ["예정", "오픈예정", "준비중", "예약기간아님", "예약기간이 아닙니다"]

# 잔여 인원 패턴 (앞 그룹이 잔여)
REMAINING_PATTERNS = [
    re.compile(r"잔여\s*[:：]?\s*(\d+)"),
    re.compile(r"남은\s*(?:인원|자리|좌석)?\s*[:：]?\s*(\d+)"),
    re.compile(r"여석\s*[:：]?\s*(\d+)"),
    re.compile(r"(\d+)\s*(?:명|석|자리)\s*(?:남음|가능|여유)"),
    re.compile(r"가능\s*(?:인원)?\s*[:：]?\s*(\d+)"),
]
# "예약 3/20", "3 / 20명", "신청 3명 / 정원 20명" 형태: (예약, 정원)
RATIO_PATTERNS = [
    re.compile(r"(\d+)\s*(?:명)?\s*/\s*(\d+)\s*(?:명)?"),
]
# 정원/예약 인원 개별 표기
CAPACITY_PATTERNS = [
    re.compile(r"(?:정원|모집인원|모집 인원|총인원|총 인원|수용인원)\s*[:：]?\s*(\d+)"),
]
RESERVED_PATTERNS = [
    re.compile(r"(?:예약인원|예약 인원|신청인원|신청 인원|접수인원|현재인원|현재 인원)\s*[:：]?\s*(\d+)"),
]

TIME_RANGE_RE = re.compile(r"(\d{1,2}\s*:\s*\d{2})\s*[~\-–]\s*(\d{1,2}\s*:\s*\d{2})")
TIME_SINGLE_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
SESSION_RE = re.compile(r"(\d+)\s*회\s*차")

# 우리동네키움포털 실사이트 달력 표기: "13 1회 개인 0 2회 개인 0 3회 개인 2 4회 개인 0"
# "잔여"라는 단어 없이 "N회 (개인|공용|단체) 남은인원" 이 반복되는 형태로, 회차 뒤에
# "차"가 붙지 않는다(SESSION_RE 는 매칭하지 못함). 마지막 정수가 그 회차의 잔여 인원이다.
ROUND_COUNT_RE = re.compile(r"(\d+)\s*회\s*(개인|공용|단체)?\s*(\d+)")


@dataclass
class Classification:
    status: SlotStatus
    remaining: int | None
    capacity: int | None
    reason: str


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_numbers(text: str, remaining_regex: str | None = None) -> tuple[int | None, int | None]:
    """텍스트에서 (잔여, 정원) 추출. 못 찾으면 None."""
    t = normalize_ws(text)
    remaining: int | None = None
    capacity: int | None = None

    if remaining_regex:
        m = re.search(remaining_regex, t)
        if m:
            remaining = int(m.group(1))

    if remaining is None:
        for pat in REMAINING_PATTERNS:
            m = pat.search(t)
            if m:
                remaining = int(m.group(1))
                break

    for pat in CAPACITY_PATTERNS:
        m = pat.search(t)
        if m:
            capacity = int(m.group(1))
            break

    if remaining is not None and capacity is None:
        # "잔여 3 / 20" 처럼 잔여 뒤에 정원이 따라오는 경우
        m = re.search(r"(\d+)\s*(?:명)?\s*/\s*(\d+)", t)
        if m and int(m.group(1)) == remaining:
            capacity = int(m.group(2))

    if remaining is None:
        reserved: int | None = None
        for pat in RESERVED_PATTERNS:
            m = pat.search(t)
            if m:
                reserved = int(m.group(1))
                break
        if reserved is None:
            for pat in RATIO_PATTERNS:
                m = pat.search(t)
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    # "잔여/정원" 표기인지 "예약/정원" 표기인지 모호: 앞에 '잔여' 가 있으면 잔여로 본다
                    prefix = t[max(0, m.start() - 6):m.start()]
                    if "잔여" in prefix or "남" in prefix or "여석" in prefix:
                        remaining, capacity = a, b
                    else:
                        reserved, capacity = a, b
                    break
        if remaining is None and reserved is not None and capacity is not None:
            remaining = max(capacity - reserved, 0)

    return remaining, capacity


def classify_text(
    text: str,
    open_keywords: list[str] | None = None,
    closed_keywords: list[str] | None = None,
    remaining_regex: str | None = None,
    clickable: bool | None = None,
    remaining: int | None = None,
    capacity: int | None = None,
) -> Classification:
    """문구 + 숫자 + 클릭 가능 여부로 상태를 판별한다.

    우선순위:
      1. 잔여 숫자가 있으면 숫자 기준 (0 -> FULL, >0 -> OPEN)
      2. 닫힘 키워드 > 열림 키워드
      3. 키워드가 없고 clickable 정보가 있으면 그것을 따름
      4. 그 외 UNKNOWN
    """
    t = normalize_ws(text)
    r2, c2 = extract_numbers(t, remaining_regex)
    remaining = remaining if remaining is not None else r2
    capacity = capacity if capacity is not None else c2
    closed_kw = list(closed_keywords or []) + CLOSED_KEYWORDS + INACTIVE_KEYWORDS
    open_kw = list(open_keywords or []) + OPEN_KEYWORDS

    if remaining is not None:
        if remaining > 0:
            return Classification(SlotStatus.OPEN, remaining, capacity, f"remaining={remaining}")
        return Classification(SlotStatus.FULL, 0, capacity, "remaining=0")

    for kw in closed_kw:
        if kw in t:
            st = SlotStatus.FULL if ("마감" in kw or "만석" in kw or "매진" in kw or "완료" in kw) else SlotStatus.CLOSED
            return Classification(st, None, capacity, f"keyword:{kw}")
    for kw in open_kw:
        if kw in t:
            return Classification(SlotStatus.OPEN, None, capacity, f"keyword:{kw}")

    if clickable is True:
        return Classification(SlotStatus.OPEN, None, capacity, "clickable")
    if clickable is False:
        return Classification(SlotStatus.CLOSED, None, capacity, "not-clickable")
    return Classification(SlotStatus.UNKNOWN, None, capacity, "no-signal")


def extract_session_label(text: str) -> str:
    """'1회차 10:00~12:00' 같은 회차/시간 라벨 추출. 없으면 정규화된 앞부분 텍스트."""
    t = normalize_ws(text)
    parts: list[str] = []
    m = SESSION_RE.search(t)
    if m:
        parts.append(f"{m.group(1)}회차")
    tr = TIME_RANGE_RE.search(t)
    if tr:
        parts.append(f"{tr.group(1).replace(' ', '')}~{tr.group(2).replace(' ', '')}")
    else:
        ts = TIME_SINGLE_RE.search(t)
        if ts:
            parts.append(ts.group(1))
    if parts:
        return " ".join(parts)
    return t[:40]


def extract_round_counts(text: str) -> list[tuple[int, str, int]]:
    """'1회 개인 0 2회 공용 33' 형태에서 (회차, 구분, 잔여인원) 목록을 추출.

    우리동네키움포털 실사이트 달력은 날짜 셀에 회차별 잔여 인원을 이렇게
    나열해 보여준다(숫자 0 = 마감, 그 외 = 잔여 인원). 매치가 없으면 빈 리스트.
    """
    out: list[tuple[int, str, int]] = []
    for m in ROUND_COUNT_RE.finditer(normalize_ws(text)):
        out.append((int(m.group(1)), m.group(2) or "", int(m.group(3))))
    return out


HEADER_REMAIN = ("잔여", "남은", "여석", "가능인원", "가능 인원", "예약가능")
HEADER_CAPACITY = ("정원", "모집", "총인원", "총 인원", "수용")
HEADER_RESERVED = ("예약인원", "예약 인원", "신청인원", "신청 인원", "접수인원", "현재", "예약자", "신청자", "신청", "예약")


def table_row_numbers(tr) -> tuple[int | None, int | None]:
    """<tr> 의 셀을 같은 표의 헤더(th) 이름과 맞춰 (잔여, 정원)을 구한다. 헤더가 없으면 (None, None)."""
    table = tr.find_parent("table")
    if table is None:
        return None, None
    header_tr = None
    for cand in table.find_all("tr"):
        if cand.find("th") is not None:
            header_tr = cand
            break
    if header_tr is None or header_tr is tr:
        return None, None
    headers: list[str] = []
    for th in header_tr.find_all(["th", "td"]):
        span = int(th.get("colspan", 1) or 1)
        headers.extend([normalize_ws(th.get_text(" "))] * span)
    cells: list[str] = []
    for td in tr.find_all(["td", "th"]):
        span = int(td.get("colspan", 1) or 1)
        cells.extend([normalize_ws(td.get_text(" "))] * span)
    remaining = capacity = reserved = None
    for h, c in zip(headers, cells):
        m = re.search(r"\d+", c)
        if not m:
            continue
        n = int(m.group(0))
        # 셀 자체에 라벨이 있으면 셀 라벨이 헤더보다 우선 (예: 예약인원 열에 '잔여 0명')
        label = c if any(k in c for k in HEADER_REMAIN + HEADER_CAPACITY + HEADER_RESERVED) else h
        if remaining is None and any(k in label for k in HEADER_REMAIN):
            remaining = n
        elif capacity is None and any(k in label for k in HEADER_CAPACITY):
            capacity = n
        elif reserved is None and any(k in label for k in HEADER_RESERVED):
            reserved = n
    if remaining is None and capacity is not None and reserved is not None:
        remaining = max(capacity - reserved, 0)
    return remaining, capacity
