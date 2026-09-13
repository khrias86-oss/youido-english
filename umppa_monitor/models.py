"""도메인 모델.

감시 대상(Target)과 감시 결과(Slot)를 정의한다. 파서는 HTML/JSON을
Slot 목록으로 변환하고, 이후 단계(diff/notify)는 Slot만 다룬다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Any


class TargetKind(str, Enum):
    KIDSCAFE = "kidscafe"   # 키즈카페 회차 예약 (달력)
    PROGRAM = "program"     # 키즈카페 프로그램 예약


class SlotStatus(str, Enum):
    OPEN = "open"           # 예약 가능(잔여 있음)
    FULL = "full"           # 마감/잔여 0
    CLOSED = "closed"       # 휴관/예약불가/기간 외
    UNKNOWN = "unknown"     # 판별 불가


BASE_URL = "https://umppa.seoul.go.kr"
KIDSCAFE_CAL_PATH = "/icare/user/kidsCafeResve/BD_selectKidsCafeResveCal.do"
PROGRAM_VIEW_PATH = "/icare/user/kidsCafeProgrm/BD_selectKidsCafeProgrm.do"
PROGRAM_LIST_PATH = "/icare/user/kidsCafeProgrm/BD_selectKidsCafeProgrmList.do"


@dataclass
class Target:
    kind: TargetKind
    id: str                      # 키즈카페: q_fcltyId (예: YF260101), 프로그램: q_progrmSn (예: 8644)
    name: str = ""
    url: str | None = None       # 직접 지정 시 우선
    dates: list[str] = field(default_factory=list)      # 'YYYY-MM-DD' 필터 (비어 있으면 전체)
    weekdays: list[int] = field(default_factory=list)   # 0=월 ... 6=일 (비어 있으면 전체)
    sessions: list[str] = field(default_factory=list)   # 회차/시간 문자열 부분일치 필터 (예: "1회차", "10:00")
    min_remaining: int = 1
    months_ahead: int = 1        # 달력에서 다음 달까지 몇 개월 탐색할지
    click_dates: bool = True     # 날짜 셀 클릭으로 회차 상세를 열어볼지
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.id}"

    def resolved_url(self) -> str:
        if self.url:
            return self.url
        if self.kind == TargetKind.KIDSCAFE:
            return f"{BASE_URL}{KIDSCAFE_CAL_PATH}?q_fcltyId={self.id}"
        return f"{BASE_URL}{PROGRAM_VIEW_PATH}?q_progrmSn={self.id}"

    def display_name(self) -> str:
        return self.name or self.key


@dataclass
class Slot:
    target_key: str
    kind: TargetKind
    date: str | None             # 'YYYY-MM-DD' (프로그램은 없을 수 있음)
    session: str                 # 회차/시간 라벨 (예: "1회차 10:00~12:00") 또는 프로그램명
    status: SlotStatus
    remaining: int | None = None
    capacity: int | None = None
    raw: str = ""                # 판별 근거 텍스트
    url: str = ""

    @property
    def key(self) -> str:
        return f"{self.target_key}|{self.date or '-'}|{self.session}"

    @property
    def is_open(self) -> bool:
        return self.status == SlotStatus.OPEN

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Slot":
        return Slot(
            target_key=d["target_key"],
            kind=TargetKind(d["kind"]),
            date=d.get("date"),
            session=d.get("session", ""),
            status=SlotStatus(d.get("status", "unknown")),
            remaining=d.get("remaining"),
            capacity=d.get("capacity"),
            raw=d.get("raw", ""),
            url=d.get("url", ""),
        )

    def weekday(self) -> int | None:
        if not self.date:
            return None
        try:
            y, m, d = (int(x) for x in self.date.split("-"))
            return date(y, m, d).weekday()
        except ValueError:
            return None


_DATE_RE = re.compile(r"(20\d{2})[-./]?(0[1-9]|1[0-2])[-./]?(0[1-9]|[12]\d|3[01])")


def normalize_date(text: str) -> str | None:
    """'20260915', '2026-09-15', '2026.09.15' -> '2026-09-15'."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
