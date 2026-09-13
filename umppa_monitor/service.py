"""백그라운드 감시 서비스 (웹 대시보드용).

scheduler.scan_once 를 별도 스레드에서 주기 실행하고, 최근 결과·로그·상태를
메모리에 보관한다. '지금 확인' 요청은 Event 로 즉시 깨운다.
"""

from __future__ import annotations

import collections
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from .browser import BrowserSession, allowed_hosts_for
from .config import AppConfig, load_config
from .models import Slot
from .notify.base import Notifier
from .notify.factory import build_notifiers
from .scheduler import in_quiet_hours, scan_once
from .state import StateStore

log = logging.getLogger(__name__)


class RingLogHandler(logging.Handler):
    def __init__(self, capacity: int = 300):
        super().__init__()
        self.buf: collections.deque[str] = collections.deque(maxlen=capacity)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buf.append(self.format(record))
        except Exception:
            pass


@dataclass
class TargetStatus:
    key: str
    name: str
    url: str
    slots: list[Slot] = field(default_factory=list)
    checked_at: float | None = None
    error: str | None = None


@dataclass
class ServiceStatus:
    running: bool = False
    busy: bool = False
    last_cycle_at: float | None = None
    next_cycle_at: float | None = None
    cycles: int = 0
    last_error: str | None = None
    targets: dict[str, TargetStatus] = field(default_factory=dict)


class MonitorService:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.cfg: AppConfig = load_config(config_path)
        self.notifiers: list[Notifier] = build_notifiers(self.cfg.notifiers)
        self.store = StateStore(self.cfg.state_dir)
        self.status = ServiceStatus()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.logs = RingLogHandler()
        logging.getLogger("umppa_monitor").addHandler(self.logs)
        self._refresh_target_status()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="umppa-monitor", daemon=True)
        self._thread.start()
        self.status.running = True

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.status.running = False

    def reload(self) -> None:
        with self._lock:
            self.cfg = load_config(self.config_path)
            self.notifiers = build_notifiers(self.cfg.notifiers)
            self.store = StateStore(self.cfg.state_dir)
            self._refresh_target_status()
        log.info("config reloaded (%d targets)", len(self.cfg.targets))

    def check_now(self) -> None:
        self._wake.set()

    # ---- internals --------------------------------------------------------
    def _refresh_target_status(self) -> None:
        new: dict[str, TargetStatus] = {}
        for t in self.cfg.targets:
            prev = self.status.targets.get(t.key)
            ts = TargetStatus(key=t.key, name=t.display_name(), url=t.resolved_url())
            if prev:
                ts.slots, ts.checked_at, ts.error = prev.slots, prev.checked_at, prev.error
            else:
                snap = self.store.load(t.key)
                if snap:
                    ts.slots = sorted(snap.slots.values(), key=lambda s: (s.date or "", s.session))
                    ts.checked_at = snap.taken_at
            new[t.key] = ts
        self.status.targets = new

    def run_cycle(self) -> None:
        with self._lock:
            cfg, store, notifiers = self.cfg, self.store, self.notifiers
        self.status.busy = True
        try:
            with BrowserSession(cfg.browser, allowed_hosts_for(cfg.targets)) as session:
                results = scan_once(cfg, store, notifiers, session)
            now = time.time()
            for t in cfg.targets:
                ts = self.status.targets.setdefault(t.key, TargetStatus(t.key, t.display_name(), t.resolved_url()))
                if t.key in results:
                    ts.slots, ts.checked_at, ts.error = results[t.key], now, None
                elif t.enabled:
                    ts.error = "수집 실패 (로그 확인)"
            self.status.last_error = None
        except Exception as e:
            self.status.last_error = f"{type(e).__name__}: {e}"
            log.exception("cycle failed: %s", e)
        finally:
            self.status.busy = False
            self.status.last_cycle_at = time.time()
            self.status.cycles += 1

    def _loop(self) -> None:
        backoff = 0
        while not self._stop.is_set():
            if in_quiet_hours(self.cfg):
                self.status.next_cycle_at = time.time() + 300
                if self._wake.wait(300):
                    self._wake.clear()
                continue
            self.run_cycle()
            backoff = 0 if self.status.last_error is None else min(max(backoff * 2, 60), self.cfg.schedule.max_backoff_sec)
            wait = self.cfg.schedule.interval_sec + random.uniform(0, self.cfg.schedule.jitter_sec) + backoff
            self.status.next_cycle_at = time.time() + wait
            if self._wake.wait(wait):
                self._wake.clear()

    def now_local(self) -> datetime:
        return datetime.now(ZoneInfo(self.cfg.browser.timezone))
