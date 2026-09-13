from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class Notifier(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, title: str, body: str, url: str | None = None) -> None: ...

    def safe_send(self, title: str, body: str, url: str | None = None) -> bool:
        try:
            self.send(title, body, url)
            return True
        except Exception as e:  # 알림 실패가 감시 루프를 죽이면 안 된다
            log.error("notifier %s failed: %s", self.name, e)
            return False
