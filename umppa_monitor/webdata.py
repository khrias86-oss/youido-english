"""웹 앱(SPA)이 읽는 스냅샷 생성과, 웹에서 고른 감시 조건(prefs) 처리.

두 방향의 데이터가 있다.

* **감시 → 웹**: 달력 화면은 "빈자리 없는 날"도 그려야 하므로 필터 이전의 전체
  슬롯이 필요하다. 알림용 스냅샷(`state/<key>.json`)은 `apply_filters` 를 거친
  뒤의 슬롯만 담기 때문에 달력 용도로는 쓸 수 없어, 매 사이클 전체 슬롯을
  `state/webdata.json` 에 따로 남기고 `build_snapshot()` 이 이를 달력용
  '날짜 × 회차' 행렬로 바꾼다.
* **웹 → 감시**: 웹에서 고른 요일/날짜/회차는 `webstate/prefs.json` 에 저장되고,
  `apply_prefs()` 가 다음 사이클의 Target 필터로 덮어쓴다. 대상별로 조건을
  따로 두어 키즈카페와 프로그램을 개별 판단한다.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import Slot, Target, TargetKind

WEBDATA_FILENAME = "webdata.json"
PREFS_FILENAME = "prefs.json"
SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# 감시 조건 (웹 UI 가 저장 -> 감시가 읽음)
# --------------------------------------------------------------------------
@dataclass
class TargetPrefs:
    """대상 하나에 대한 감시 조건. 비어 있는 목록은 '제한 없음'."""
    enabled: bool = True
    weekdays: list[int] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    min_remaining: int = 1


@dataclass
class Prefs:
    version: int = SCHEMA_VERSION
    updated_at: float = 0.0
    targets: dict[str, TargetPrefs] = field(default_factory=dict)
    programs: list[str] = field(default_factory=list)   # 웹에서 고른 q_progrmSn 목록

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "targets": {k: asdict(v) for k, v in self.targets.items()},
            "programs": list(self.programs),
        }


def _as_int_list(raw: Any, lo: int, hi: int) -> list[int]:
    out: list[int] = []
    for v in raw if isinstance(raw, list) else []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if lo <= n <= hi and n not in out:
            out.append(n)
    return sorted(out)


def _as_str_list(raw: Any, limit: int = 200) -> list[str]:
    out: list[str] = []
    for v in raw if isinstance(raw, list) else []:
        s = str(v).strip()
        if s and s not in out:
            out.append(s[:80])
        if len(out) >= limit:
            break
    return out


def parse_prefs(raw: Any) -> Prefs:
    """외부(웹 UI/파일)에서 온 dict 를 Prefs 로 정규화. 신뢰하지 않고 값을 제한한다."""
    if not isinstance(raw, dict):
        return Prefs()
    targets: dict[str, TargetPrefs] = {}
    for key, tv in (raw.get("targets") or {}).items():
        if not isinstance(tv, dict):
            continue
        try:
            min_remaining = max(1, min(999, int(tv.get("min_remaining", 1))))
        except (TypeError, ValueError):
            min_remaining = 1
        targets[str(key)[:80]] = TargetPrefs(
            enabled=bool(tv.get("enabled", True)),
            weekdays=_as_int_list(tv.get("weekdays"), 0, 6),
            dates=[d for d in _as_str_list(tv.get("dates")) if len(d) == 10 and d[4] == "-"],
            sessions=_as_str_list(tv.get("sessions"), 60),
            min_remaining=min_remaining,
        )
    try:
        updated_at = float(raw.get("updated_at", 0) or 0)
    except (TypeError, ValueError):
        updated_at = 0.0
    return Prefs(
        version=SCHEMA_VERSION,
        updated_at=updated_at,
        targets=targets,
        programs=[p for p in _as_str_list(raw.get("programs"), 40) if p.isalnum()],
    )


def load_prefs(path: str | Path) -> Prefs | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return parse_prefs(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def save_prefs(path: str | Path, prefs: Prefs) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prefs.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


def apply_prefs(cfg: AppConfig, prefs: Prefs | None, programs: list[dict[str, Any]] | None = None) -> AppConfig:
    """웹에서 고른 조건을 설정에 덮어쓴다. 대상별로 따로 적용한다."""
    if prefs is None:
        return cfg
    by_name = {str(p.get("id")): str(p.get("name") or "") for p in (programs or [])}

    for t in cfg.targets:
        tp = prefs.targets.get(t.key)
        if tp is None:
            continue
        t.enabled = tp.enabled
        t.weekdays = list(tp.weekdays)
        t.dates = list(tp.dates)
        t.sessions = list(tp.sessions)
        t.min_remaining = tp.min_remaining

    # 웹에서 새로 고른 프로그램을 감시 대상으로 추가
    known = {t.key for t in cfg.targets}
    for pid in prefs.programs:
        key = f"{TargetKind.PROGRAM.value}:{pid}"
        if key in known:
            continue
        tp = prefs.targets.get(key) or TargetPrefs()
        cfg.targets.append(Target(
            kind=TargetKind.PROGRAM, id=pid, name=by_name.get(pid, ""),
            weekdays=list(tp.weekdays), dates=list(tp.dates), sessions=list(tp.sessions),
            min_remaining=tp.min_remaining, enabled=tp.enabled,
        ))
    return cfg


def prefs_from_config(cfg: AppConfig) -> Prefs:
    """설정 파일의 현재 필터를 Prefs 형태로 (웹 UI 의 초기 상태용)."""
    return Prefs(
        updated_at=0.0,
        targets={t.key: TargetPrefs(enabled=t.enabled, weekdays=list(t.weekdays), dates=list(t.dates),
                                    sessions=list(t.sessions), min_remaining=t.min_remaining)
                 for t in cfg.targets},
        programs=[t.id for t in cfg.targets if t.kind == TargetKind.PROGRAM],
    )


# --------------------------------------------------------------------------
# 감시 결과 -> 달력용 스냅샷
# --------------------------------------------------------------------------
def save_webdata(state_dir: str | Path, results: dict[str, list[Slot]],
                 notes: dict[str, str] | None = None) -> Path:
    """필터 이전의 전체 슬롯을 달력용으로 누적 저장한다.

    이번 사이클에서 확인하지 못한 대상(일시 오류 등)의 직전 값은 남겨 두고,
    대신 실패 이유(notes)를 함께 기록해 화면이 빈 채로 남지 않게 한다.
    """
    path = Path(state_dir) / WEBDATA_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"targets": {}}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev.get("targets"), dict):
                data["targets"] = prev["targets"]
        except (json.JSONDecodeError, OSError):
            pass
    now = time.time()
    notes = notes or {}
    for key, slots in results.items():
        data["targets"][key] = {"checked_at": now, "slots": [s.to_dict() for s in slots],
                                "error": notes.get(key, "")}
    # 수집 자체가 실패해 results 에 없는 대상은 직전 슬롯을 유지하되 이유를 덧붙인다
    for key, msg in notes.items():
        if key not in results:
            entry = data["targets"].setdefault(key, {"checked_at": None, "slots": []})
            entry["error"] = msg
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def load_webdata(state_dir: str | Path) -> dict[str, Any]:
    path = Path(state_dir) / WEBDATA_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("targets", {}) if isinstance(data, dict) else {}


def session_sort_key(label: str) -> tuple[int, str]:
    """'1회차 공용' < '2회차 개인' < '개별' 처럼 회차 번호 우선으로 정렬."""
    num = ""
    for ch in label:
        if ch.isdigit():
            num += ch
        elif num:
            break
    return (int(num) if num else 999, label)


def _day_entry(slots: list[Slot]) -> dict[str, Any]:
    return {
        "slots": [
            {"session": s.session, "status": s.status.value,
             "remaining": s.remaining, "capacity": s.capacity}
            for s in sorted(slots, key=lambda x: session_sort_key(x.session))
        ],
        "open": sum(1 for s in slots if s.is_open),
        "seats": sum(s.remaining or 0 for s in slots if s.is_open),
    }


def build_target_view(target: Target, entry: dict[str, Any]) -> dict[str, Any]:
    """한 대상의 슬롯 목록을 '날짜 → 회차들' 형태로 묶는다."""
    slots = [Slot.from_dict(d) for d in entry.get("slots", [])]
    by_date: dict[str, list[Slot]] = {}
    undated: list[Slot] = []
    for s in slots:
        if s.date:
            by_date.setdefault(s.date, []).append(s)
        else:
            undated.append(s)
    sessions = sorted({s.session for s in slots if s.session != "day"}, key=session_sort_key)
    days = {d: _day_entry(v) for d, v in sorted(by_date.items())}
    return {
        "key": target.key,
        "kind": target.kind.value,
        "name": target.display_name(),
        "url": target.resolved_url(),
        "enabled": target.enabled,
        "checked_at": entry.get("checked_at"),
        "error": entry.get("error") or "",
        "sessions": sessions,
        "days": days,
        "undated": [{"session": s.session, "status": s.status.value, "remaining": s.remaining}
                    for s in undated],
        "open_count": sum(v["open"] for v in days.values()) + sum(1 for s in undated if s.is_open),
        "total": len(slots),
    }


def build_snapshot(cfg: AppConfig, state_dir: str | Path, prefs: Prefs | None,
                   programs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """SPA 가 읽는 data.json 전체."""
    stored = load_webdata(state_dir)
    targets = [build_target_view(t, stored.get(t.key, {})) for t in cfg.targets]
    return {
        "version": SCHEMA_VERSION,
        "generated_at": time.time(),
        "tz": cfg.browser.timezone,
        "interval_sec": cfg.schedule.interval_sec,
        "quiet_hours": list(cfg.schedule.quiet_hours),
        "prefs": (prefs or prefs_from_config(cfg)).to_dict(),
        "targets": targets,
        "programs": programs or [],
    }
