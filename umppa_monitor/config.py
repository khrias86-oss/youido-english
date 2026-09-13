"""YAML 설정 로더.

설정 파일 예시는 config.example.yaml 참조. 비밀값(토큰 등)은
환경변수로도 줄 수 있다 (예: UMPPA_TELEGRAM_TOKEN).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Target, TargetKind


@dataclass
class NotifierConfig:
    type: str                                   # console | telegram | discord | slack | email | ntfy
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserConfig:
    headless: bool = True
    executable_path: str | None = None          # 지정 시 해당 크로미움 사용
    storage_state: str | None = None            # 로그인 쿠키 저장 파일 (선택)
    timeout_ms: int = 30000
    user_agent: str | None = None
    locale: str = "ko-KR"
    timezone: str = "Asia/Seoul"
    allowed_hosts: list[str] = field(default_factory=list)  # 비어 있으면 대상 URL 호스트 + seoul.go.kr 만 허용


@dataclass
class ScheduleConfig:
    interval_sec: int = 300                     # 기본 5분
    jitter_sec: int = 30
    quiet_hours: list[str] = field(default_factory=list)  # ["00:00-07:00"] 감시 중단 구간
    max_backoff_sec: int = 1800
    notify_on_close: bool = False               # 열림→마감 전환도 알릴지
    renotify_after_min: int = 0                 # 0이면 열림 상태 재알림 없음


@dataclass
class ParserOverrides:
    """사이트 구조가 확인된 뒤 정밀 선택자를 지정하기 위한 옵션 (모두 선택)."""
    calendar_cell_selector: str | None = None   # 예: "table.calendar td"
    date_attr: str | None = None                # 예: "data-date"
    slot_selector: str | None = None            # 날짜 클릭 후 회차 목록 셀렉터
    next_month_selector: str | None = None
    open_keywords: list[str] = field(default_factory=list)
    closed_keywords: list[str] = field(default_factory=list)
    remaining_regex: str | None = None


@dataclass
class AppConfig:
    targets: list[Target]
    notifiers: list[NotifierConfig]
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    parser: ParserOverrides = field(default_factory=ParserOverrides)
    state_dir: str = "state"
    artifacts_dir: str = "artifacts"
    log_level: str = "INFO"


def _expand_env(value: Any) -> Any:
    """문자열 값 안의 ${ENV_VAR} 를 환경변수로 치환."""
    if isinstance(value, str) and "${" in value:
        out = value
        for part in value.split("${")[1:]:
            name = part.split("}", 1)[0]
            out = out.replace("${" + name + "}", os.environ.get(name, ""))
        return out
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _parse_target(raw: dict[str, Any]) -> Target:
    kind = TargetKind(str(raw.get("type", "kidscafe")).lower())
    return Target(
        kind=kind,
        id=str(raw["id"]),
        name=str(raw.get("name", "")),
        url=raw.get("url"),
        dates=[str(d) for d in raw.get("dates", [])],
        weekdays=[int(w) for w in raw.get("weekdays", [])],
        sessions=[str(s) for s in raw.get("sessions", [])],
        min_remaining=int(raw.get("min_remaining", 1)),
        months_ahead=int(raw.get("months_ahead", 1)),
        click_dates=bool(raw.get("click_dates", True)),
        enabled=bool(raw.get("enabled", True)),
    )


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = _expand_env(data)
    base_dir = path.resolve().parent

    def _rel(v: str | None) -> str | None:
        if not v:
            return v
        pv = Path(v)
        return str(pv if pv.is_absolute() else base_dir / pv)

    targets = [_parse_target(t) for t in data.get("targets", [])]
    if not targets:
        raise ValueError("설정에 targets 가 하나 이상 필요합니다.")

    notifiers = []
    for n in data.get("notifiers", []) or []:
        n = dict(n)
        ntype = str(n.pop("type"))
        notifiers.append(NotifierConfig(type=ntype, options=n))
    if not notifiers:
        notifiers.append(NotifierConfig(type="console"))

    b = data.get("browser", {}) or {}
    browser = BrowserConfig(
        headless=bool(b.get("headless", True)),
        executable_path=b.get("executable_path") or os.environ.get("UMPPA_CHROMIUM_PATH"),
        storage_state=_rel(b.get("storage_state")),
        allowed_hosts=[str(h) for h in b.get("allowed_hosts", [])],
        timeout_ms=int(b.get("timeout_ms", 30000)),
        user_agent=b.get("user_agent"),
        locale=b.get("locale", "ko-KR"),
        timezone=b.get("timezone", "Asia/Seoul"),
    )

    s = data.get("schedule", {}) or {}
    schedule = ScheduleConfig(
        interval_sec=int(s.get("interval_sec", 300)),
        jitter_sec=int(s.get("jitter_sec", 30)),
        quiet_hours=[str(q) for q in s.get("quiet_hours", [])],
        max_backoff_sec=int(s.get("max_backoff_sec", 1800)),
        notify_on_close=bool(s.get("notify_on_close", False)),
        renotify_after_min=int(s.get("renotify_after_min", 0)),
    )

    p = data.get("parser", {}) or {}
    parser = ParserOverrides(
        calendar_cell_selector=p.get("calendar_cell_selector"),
        date_attr=p.get("date_attr"),
        slot_selector=p.get("slot_selector"),
        next_month_selector=p.get("next_month_selector"),
        open_keywords=list(p.get("open_keywords", [])),
        closed_keywords=list(p.get("closed_keywords", [])),
        remaining_regex=p.get("remaining_regex"),
    )

    return AppConfig(
        targets=targets,
        notifiers=notifiers,
        browser=browser,
        schedule=schedule,
        parser=parser,
        state_dir=_rel(str(data.get("state_dir", "state"))),
        artifacts_dir=_rel(str(data.get("artifacts_dir", "artifacts"))),
        log_level=str(data.get("log_level", "INFO")),
    )
