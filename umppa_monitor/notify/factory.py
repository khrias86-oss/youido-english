from __future__ import annotations

from ..config import NotifierConfig
from .base import Notifier
from .channels import (ConsoleNotifier, DiscordNotifier, EmailNotifier, NtfyNotifier,
                       SlackNotifier, TelegramNotifier)


def build_notifiers(cfgs: list[NotifierConfig]) -> list[Notifier]:
    out: list[Notifier] = []
    for c in cfgs:
        t = c.type.lower()
        o = c.options
        if t == "console":
            out.append(ConsoleNotifier())
        elif t == "telegram":
            out.append(TelegramNotifier(o.get("token", ""), o.get("chat_id", "")))
        elif t == "discord":
            out.append(DiscordNotifier(o.get("webhook_url", "")))
        elif t == "slack":
            out.append(SlackNotifier(o.get("webhook_url", "")))
        elif t == "ntfy":
            out.append(NtfyNotifier(o.get("topic", ""), o.get("server", "https://ntfy.sh"), o.get("token")))
        elif t == "email":
            out.append(EmailNotifier(o.get("smtp_host", ""), int(o.get("smtp_port", 587)), o.get("username", ""),
                                     o.get("password", ""), list(o.get("to", [])), o.get("from"), bool(o.get("use_tls", True))))
        else:
            raise ValueError(f"알 수 없는 notifier type: {c.type}")
    return out
