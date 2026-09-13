"""config.yaml 을 원본(YAML dict) 수준에서 수정하는 도우미 (웹 UI 용).

${ENV} 참조는 그대로 보존된다 (환경변수 치환은 load_config 시점에만 일어남).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def read_raw(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"targets": [], "notifiers": [{"type": "console"}]}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def write_raw(path: str | Path, data: dict[str, Any]) -> None:
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def add_target(path: str | Path, kind: str, id_: str, name: str = "", weekdays: list[int] | None = None,
               sessions: list[str] | None = None, months_ahead: int = 1, min_remaining: int = 1) -> None:
    data = read_raw(path)
    targets = data.setdefault("targets", []) or []
    for t in targets:
        if str(t.get("type", "kidscafe")) == kind and str(t.get("id")) == str(id_):
            t["enabled"] = True
            if name:
                t["name"] = name
            write_raw(path, data)
            return
    entry: dict[str, Any] = {"type": kind, "id": id_}
    if name:
        entry["name"] = name
    if weekdays:
        entry["weekdays"] = weekdays
    if sessions:
        entry["sessions"] = sessions
    if months_ahead != 1:
        entry["months_ahead"] = months_ahead
    if min_remaining != 1:
        entry["min_remaining"] = min_remaining
    targets.append(entry)
    data["targets"] = targets
    write_raw(path, data)


def set_target_enabled(path: str | Path, key: str, enabled: bool) -> bool:
    data = read_raw(path)
    for t in data.get("targets", []) or []:
        if f"{t.get('type', 'kidscafe')}:{t.get('id')}" == key:
            t["enabled"] = enabled
            write_raw(path, data)
            return True
    return False


def remove_target(path: str | Path, key: str) -> bool:
    data = read_raw(path)
    before = data.get("targets", []) or []
    after = [t for t in before if f"{t.get('type', 'kidscafe')}:{t.get('id')}" != key]
    if len(after) == len(before):
        return False
    data["targets"] = after
    write_raw(path, data)
    return True


def set_schedule(path: str | Path, interval_sec: int | None = None, quiet_hours: list[str] | None = None) -> None:
    data = read_raw(path)
    sch = data.setdefault("schedule", {}) or {}
    if interval_sec is not None:
        sch["interval_sec"] = max(60, int(interval_sec))
    if quiet_hours is not None:
        sch["quiet_hours"] = quiet_hours
    data["schedule"] = sch
    write_raw(path, data)
