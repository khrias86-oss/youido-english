"""알림 채널 구현: console, telegram, discord, slack, ntfy, email."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

import requests

from .base import Notifier

log = logging.getLogger(__name__)
_TIMEOUT = 15


class ConsoleNotifier(Notifier):
    name = "console"

    def send(self, title: str, body: str, url: str | None = None) -> None:
        line = "=" * 60
        print(f"\n{line}\n[알림] {title}\n{body}\n{url or ''}\n{line}\n", flush=True)


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise ValueError("telegram: token/chat_id 필요")
        self.token, self.chat_id = token, str(chat_id)

    def send(self, title: str, body: str, url: str | None = None) -> None:
        text = f"*{_md_escape(title)}*\n{_md_escape(body)}"
        if url:
            text += f"\n{_md_escape(url)}"
        r = requests.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "MarkdownV2",
                  "disable_web_page_preview": True},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()


def _md_escape(s: str) -> str:
    out = []
    for ch in s:
        out.append("\\" + ch if ch in r"_*[]()~`>#+-=|{}.!\\" else ch)
    return "".join(out)


class DiscordNotifier(Notifier):
    name = "discord"

    def __init__(self, webhook_url: str):
        if not webhook_url:
            raise ValueError("discord: webhook_url 필요")
        self.webhook_url = webhook_url

    def send(self, title: str, body: str, url: str | None = None) -> None:
        content = f"**{title}**\n{body}" + (f"\n{url}" if url else "")
        r = requests.post(self.webhook_url, json={"content": content[:1900]}, timeout=_TIMEOUT)
        r.raise_for_status()


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(self, webhook_url: str):
        if not webhook_url:
            raise ValueError("slack: webhook_url 필요")
        self.webhook_url = webhook_url

    def send(self, title: str, body: str, url: str | None = None) -> None:
        text = f"*{title}*\n{body}" + (f"\n{url}" if url else "")
        r = requests.post(self.webhook_url, json={"text": text}, timeout=_TIMEOUT)
        r.raise_for_status()


class NtfyNotifier(Notifier):
    """https://ntfy.sh - 앱 설치 후 토픽 구독만으로 푸시 수신 가능."""
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh", token: str | None = None):
        if not topic:
            raise ValueError("ntfy: topic 필요")
        self.url = f"{server.rstrip('/')}/{topic}"
        self.token = token

    def send(self, title: str, body: str, url: str | None = None) -> None:
        headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore") or "umppa-monitor", "Priority": "high", "Tags": "tada"}
        if url:
            headers["Click"] = url
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = requests.post(self.url, data=f"{title}\n{body}".encode("utf-8"), headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str,
                 to: list[str], from_addr: str | None = None, use_tls: bool = True):
        if not (smtp_host and username and password and to):
            raise ValueError("email: smtp_host/username/password/to 필요")
        self.host, self.port = smtp_host, int(smtp_port)
        self.username, self.password = username, password
        self.to = list(to)
        self.from_addr = from_addr or username
        self.use_tls = use_tls

    def send(self, title: str, body: str, url: str | None = None) -> None:
        msg = MIMEText(body + (f"\n\n{url}" if url else ""), "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to)
        with smtplib.SMTP(self.host, self.port, timeout=_TIMEOUT) as s:
            if self.use_tls:
                s.starttls()
            s.login(self.username, self.password)
            s.sendmail(self.from_addr, self.to, msg.as_string())
