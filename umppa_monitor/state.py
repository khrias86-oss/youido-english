"""스냅샷 저장 및 변화 감지.

state/<target_key>.json 에 마지막 관측 Slot 들을 저장하고, 새 관측과 비교해
  - opened: 이전에 열려 있지 않았는데(없었거나 마감/불가) 지금 열린 슬롯
  - closed: 이전에 열려 있었는데 지금 닫힌 슬롯
  - still_open: 계속 열려 있는 슬롯 (재알림 판단용)
을 계산한다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .models import Slot


@dataclass
class Snapshot:
    taken_at: float
    slots: dict[str, Slot]
    last_notified: dict[str, float] = field(default_factory=dict)   # slot key -> epoch


@dataclass
class Diff:
    opened: list[Slot] = field(default_factory=list)
    closed: list[Slot] = field(default_factory=list)
    still_open: list[Slot] = field(default_factory=list)
    first_run: bool = False


class StateStore:
    def __init__(self, state_dir: str | Path):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, target_key: str) -> Path:
        return self.dir / (target_key.replace(":", "_").replace("/", "_") + ".json")

    def load(self, target_key: str) -> Snapshot | None:
        p = self._path(target_key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        slots = {k: Slot.from_dict(v) for k, v in data.get("slots", {}).items()}
        return Snapshot(taken_at=float(data.get("taken_at", 0)), slots=slots,
                        last_notified=dict(data.get("last_notified", {})))

    def save(self, target_key: str, snap: Snapshot) -> None:
        data = {
            "taken_at": snap.taken_at,
            "slots": {k: s.to_dict() for k, s in snap.slots.items()},
            "last_notified": snap.last_notified,
        }
        self._path(target_key).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def compute_diff(prev: Snapshot | None, current: list[Slot]) -> Diff:
    diff = Diff(first_run=prev is None)
    prev_slots = prev.slots if prev else {}
    cur_map = {s.key: s for s in current}
    for k, s in cur_map.items():
        p = prev_slots.get(k)
        if s.is_open:
            if p is None or not p.is_open:
                diff.opened.append(s)
            else:
                diff.still_open.append(s)
    for k, p in prev_slots.items():
        c = cur_map.get(k)
        if p.is_open and (c is None or not c.is_open):
            diff.closed.append(c if c is not None else p)
    return diff


def next_snapshot(prev: Snapshot | None, current: list[Slot], notified_keys: list[str]) -> Snapshot:
    now = time.time()
    last = dict(prev.last_notified) if prev else {}
    for k in notified_keys:
        last[k] = now
    # 더 이상 존재하지 않는 슬롯의 알림 기록은 정리
    cur_keys = {s.key for s in current}
    last = {k: v for k, v in last.items() if k in cur_keys}
    return Snapshot(taken_at=now, slots={s.key: s for s in current}, last_notified=last)
