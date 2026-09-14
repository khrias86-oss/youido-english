"""감시 루프.

한 사이클: 각 target 수집 -> 파싱 -> 필터 -> 이전 스냅샷과 diff -> 알림 -> 스냅샷 저장.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .browser import BrowserSession, allowed_hosts_for, fetch_target
from .config import AppConfig
from .models import Slot, Target
from .notify.base import Notifier
from .notify.format import format_closed, format_opened
from .scanner import apply_filters, is_notifiable, slots_from_result
from .state import StateStore, compute_diff, next_snapshot
from .webdata import save_webdata

log = logging.getLogger(__name__)


def in_quiet_hours(cfg: AppConfig, now: datetime | None = None) -> bool:
    if not cfg.schedule.quiet_hours:
        return False
    now = now or datetime.now(ZoneInfo(cfg.browser.timezone))
    cur = now.hour * 60 + now.minute
    for rng in cfg.schedule.quiet_hours:
        try:
            a, b = rng.split("-")
            ah, am = (int(x) for x in a.split(":"))
            bh, bm = (int(x) for x in b.split(":"))
        except ValueError:
            continue
        start, end = ah * 60 + am, bh * 60 + bm
        if start <= end:
            if start <= cur < end:
                return True
        else:  # 자정을 넘는 구간
            if cur >= start or cur < end:
                return True
    return False


def scan_once(cfg: AppConfig, store: StateStore, notifiers: list[Notifier],
              session: BrowserSession, artifacts_dir: str | None = None) -> dict[str, list[Slot]]:
    """모든 target 을 1회 감시하고 target_key -> 필터를 거친 슬롯 목록을 반환."""
    out: dict[str, list[Slot]] = {}
    unfiltered: dict[str, list[Slot]] = {}
    notes: dict[str, str] = {}      # 화면에 이유를 보여주기 위한 대상별 실패 메모
    for target in cfg.targets:
        if not target.enabled:
            continue
        try:
            result = fetch_target(session, target, cfg.parser, artifacts_dir)
        except Exception as e:
            log.error("fetch failed for %s: %s", target.key, e)
            notes[target.key] = f"예약 페이지를 열지 못했습니다 ({type(e).__name__})"
            continue
        if result.errors:
            log.warning("%s fetch warnings: %s", target.key, "; ".join(result.errors)[:500])
        all_slots = slots_from_result(result, cfg.parser)
        slots = apply_filters(all_slots, target)
        out[target.key] = slots
        unfiltered[target.key] = all_slots
        open_cnt = sum(1 for s in slots if s.is_open)
        log.info("%s: parsed %d slots (%d after filter, %d open)", target.key, len(all_slots), len(slots), open_cnt)
        if not all_slots:
            log.warning("%s: 슬롯을 하나도 파싱하지 못했습니다. `umppa-monitor inspect` 로 페이지 구조를 확인하세요.", target.key)
            notes[target.key] = ("페이지는 열렸지만 회차 정보를 읽지 못했습니다. "
                                 "사이트 점검 중이거나 표기 방식이 바뀐 것일 수 있습니다.")
        elif result.errors:
            # '다음 달 이동 버튼 없음' 은 이번 달만 보면 되는 상황이라 사용자에게 알릴 일이 아니다.
            real = [e for e in result.errors if "next-month" not in e]
            if real:
                notes[target.key] = f"일부 수집 실패: {'; '.join(real)[:200]}"

        prev = store.load(target.key)
        diff = compute_diff(prev, slots)
        _notify(cfg, target, diff, prev.last_notified if prev else {}, notifiers, store, slots)
    # 달력 화면은 '빈자리 없는 날'도 그려야 해서, 필터 이전의 전체 슬롯을 따로 남긴다.
    if unfiltered or notes:
        save_webdata(cfg.state_dir, unfiltered, notes)
    return out


def _notify(cfg, target: Target, diff, last_notified: dict[str, float], notifiers, store, slots) -> None:
    now = time.time()
    to_open = [s for s in diff.opened if is_notifiable(s, target)]
    renotify_sec = cfg.schedule.renotify_after_min * 60
    if renotify_sec > 0:
        for s in diff.still_open:
            if is_notifiable(s, target) and now - last_notified.get(s.key, 0) >= renotify_sec:
                to_open.append(s)
    notified: list[str] = []
    if to_open:
        title, body, url = format_opened(target, to_open)
        log.info("OPEN %s: %s", target.key, body.replace("\n", " | "))
        for n in notifiers:
            n.safe_send(title, body, url)
        notified = [s.key for s in to_open]
    if cfg.schedule.notify_on_close and diff.closed and not diff.first_run:
        title, body, url = format_closed(target, diff.closed)
        for n in notifiers:
            n.safe_send(title, body, url)
    store.save(target.key, next_snapshot(store.load(target.key), slots, notified))


def run_loop(cfg: AppConfig, notifiers: list[Notifier], once: bool = False) -> None:
    store = StateStore(cfg.state_dir)
    backoff = 0
    while True:
        if in_quiet_hours(cfg):
            log.info("quiet hours - sleeping 5 min")
            if once:
                return
            time.sleep(300)
            continue
        started = time.time()
        try:
            with BrowserSession(cfg.browser, allowed_hosts_for(cfg.targets)) as session:
                scan_once(cfg, store, notifiers, session)
            backoff = 0
        except Exception as e:
            backoff = min(max(backoff * 2, 60), cfg.schedule.max_backoff_sec)
            log.exception("cycle failed (%s); backoff %ss", e, backoff)
        if once:
            return
        elapsed = time.time() - started
        wait = cfg.schedule.interval_sec + random.uniform(0, cfg.schedule.jitter_sec) + backoff - elapsed
        wait = max(wait, 5)
        log.info("next check in %.0fs", wait)
        time.sleep(wait)
