"""모바일 우선 HTML 렌더러. 웹 대시보드와 GitHub Pages 정적 상태 페이지가 공유한다."""

from __future__ import annotations

import html
import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import Slot, SlotStatus

WEEKDAY_KO = "월화수목금토일"

CSS = """
:root{--bg:#f6f7fb;--card:#fff;--text:#1a1d29;--muted:#6b7280;--open:#0f9d58;--full:#c62828;--closed:#9aa0a6;--accent:#3b5bdb;--line:#e5e7eb}
@media (prefers-color-scheme:dark){:root{--bg:#0f1117;--card:#181b25;--text:#e8eaf0;--muted:#9aa3b2;--line:#2a2f3d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",Roboto,sans-serif;padding:12px 16px 40px;max-width:720px;margin-inline:auto}
h1{font-size:20px;margin:8px 0 4px}h2{font-size:17px;margin:0 0 8px}.sub{color:var(--muted);font-size:13px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;color:#fff}
.b-open{background:var(--open)}.b-full{background:var(--full)}.b-closed{background:var(--closed)}.b-unknown{background:#b08d00}
.slot{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--line);font-size:15px}
.slot:first-of-type{border-top:0}.slot .d{font-weight:600}.slot .s{color:var(--muted);font-size:13px}
.btn{display:inline-block;background:var(--accent);color:#fff;border:0;border-radius:10px;padding:10px 14px;font-size:15px;text-decoration:none;cursor:pointer}
.btn.sec{background:transparent;color:var(--accent);border:1px solid var(--accent)}.btn.danger{background:var(--full)}
form.inline{display:inline}input,select{font-size:16px;padding:10px;border:1px solid var(--line);border-radius:8px;width:100%;background:var(--card);color:var(--text)}
label{display:block;font-size:13px;color:var(--muted);margin:8px 0 4px}.muted{color:var(--muted);font-size:13px}
.empty{color:var(--muted);text-align:center;padding:12px}pre{white-space:pre-wrap;font-size:12px;background:var(--bg);padding:8px;border-radius:8px;max-height:50vh;overflow:auto}
.nav{display:flex;gap:8px;margin:8px 0 12px;flex-wrap:wrap}.nav a{font-size:14px}
.err{color:var(--full);font-size:13px}.ok{color:var(--open);font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
"""

MANIFEST = {
    "name": "키즈카페 빈자리 감시", "short_name": "키즈카페", "start_url": "./", "display": "standalone",
    "background_color": "#f6f7fb", "theme_color": "#3b5bdb",
    "icons": [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}],
}
ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#3b5bdb"/>'
            '<text x="32" y="42" font-size="30" text-anchor="middle" fill="#fff" font-family="sans-serif">🎈</text></svg>')


def fmt_ts(ts: float | None, tz: str = "Asia/Seoul") -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime("%m/%d %H:%M")


def fmt_date(d: str | None) -> str:
    if not d:
        return "날짜 미상"
    try:
        y, m, dd = (int(x) for x in d.split("-"))
        wd = datetime(y, m, dd).weekday()
        return f"{m}/{dd}({WEEKDAY_KO[wd]})"
    except ValueError:
        return d


def page(title: str, body: str, head_extra: str = "", refresh_sec: int | None = None) -> str:
    refresh = f'<meta http-equiv="refresh" content="{refresh_sec}">' if refresh_sec else ""
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#3b5bdb"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="manifest.webmanifest"><link rel="icon" href="icon.svg">
<title>{html.escape(title)}</title>{refresh}<style>{CSS}</style>{head_extra}</head><body>{body}</body></html>"""


def slot_row(s: Slot) -> str:
    cls = {"open": "b-open", "full": "b-full", "closed": "b-closed"}.get(s.status.value, "b-unknown")
    lab = {"open": "가능", "full": "마감", "closed": "불가"}.get(s.status.value, "?")
    rem = ""
    if s.remaining is not None:
        rem = f" · 잔여 {s.remaining}" + (f"/{s.capacity}" if s.capacity is not None else "")
    sess = "" if s.session == "day" else html.escape(s.session)
    return (f'<div class="slot"><div><span class="d">{fmt_date(s.date)}</span> '
            f'<span class="s">{sess}{rem}</span></div><span class="badge {cls}">{lab}</span></div>')


def target_card(name: str, url: str, slots: list[Slot], checked_at: float | None, error: str | None,
                tz: str, show_all: bool = False, key: str | None = None, enabled: bool = True,
                actions_html: str = "") -> str:
    open_slots = [s for s in slots if s.status == SlotStatus.OPEN]
    shown = slots if show_all else open_slots
    rows = "".join(slot_row(s) for s in shown[:60]) or f'<div class="empty">{"빈자리 없음" if slots else "아직 확인 전"}</div>'
    n_open = len(open_slots)
    badge = f'<span class="badge b-open">{n_open}건 가능</span>' if n_open else '<span class="badge b-closed">0건</span>'
    err = f'<div class="err">{html.escape(error)}</div>' if error else ""
    dis = "" if enabled else ' <span class="badge b-closed">중지</span>'
    return f"""<div class="card"><div class="row"><h2>{html.escape(name)}{dis}</h2>{badge}</div>
<div class="muted">마지막 확인 {fmt_ts(checked_at, tz)} · 전체 {len(slots)}개 슬롯 · <a href="{html.escape(url)}" target="_blank" rel="noopener">예약 페이지 열기</a></div>
{err}{rows}{actions_html}</div>"""


def status_json(targets: list[dict[str, Any]], generated_at: float, extra: dict[str, Any] | None = None) -> str:
    data = {"generated_at": generated_at, "targets": targets}
    if extra:
        data.update(extra)
    return json.dumps(data, ensure_ascii=False, indent=1)


def static_status_page(target_items: list[tuple[str, str, list[Slot], float | None]], tz: str,
                       generated_at: float | None = None, source_url: str | None = None) -> str:
    """GitHub Pages 용 정적 페이지: 대상별 열린 슬롯 + 전체 슬롯 접기."""
    generated_at = generated_at or time.time()
    cards = []
    for name, url, slots, checked_at in target_items:
        cards.append(target_card(name, url, slots, checked_at, None, tz))
        all_rows = "".join(slot_row(s) for s in slots)
        if all_rows:
            cards.append(f'<details class="card"><summary class="muted">{html.escape(name)} 전체 슬롯 보기</summary>{all_rows}</details>')
    src = f' · <a href="{html.escape(source_url)}">설정/실행 로그</a>' if source_url else ""
    body = f"""<h1>키즈카페 빈자리 현황</h1>
<div class="sub">갱신 {fmt_ts(generated_at, tz)} (자동 새로고침){src}</div>
{''.join(cards) or '<div class="card empty">감시 대상이 없습니다.</div>'}
<div class="muted">알림은 텔레그램/ntfy 로 전송됩니다. 이 페이지는 마지막 실행 결과를 보여줍니다.</div>"""
    return page("키즈카페 빈자리 현황", body, refresh_sec=120)
