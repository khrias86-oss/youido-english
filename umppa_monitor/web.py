"""모바일용 웹 대시보드 (FastAPI).

  umppa-monitor serve -c config.yaml --port 8000
환경변수:
  UMPPA_WEB_PASSWORD  로그인 비밀번호 (미설정 시 인증 없음 — 로컬 전용)
  UMPPA_WEB_SECRET    쿠키 서명 비밀 (미설정 시 프로세스마다 랜덤)
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import threading
import time
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import config_store
from .models import Target, TargetKind
from .render_html import ICON_SVG, MANIFEST, fmt_ts, page, target_card
from .service import MonitorService

COOKIE = "umppa_session"


def _token(secret: str) -> str:
    return hmac.new(secret.encode(), b"umppa-web", hashlib.sha256).hexdigest()


def create_app(config_path: str, start_monitor: bool = True) -> FastAPI:
    service = MonitorService(config_path)
    password = os.environ.get("UMPPA_WEB_PASSWORD", "")
    secret = os.environ.get("UMPPA_WEB_SECRET") or secrets.token_hex(16)
    app = FastAPI(title="umppa-monitor", docs_url=None, redoc_url=None)
    app.state.service = service

    if start_monitor:
        service.start()

    # ---- auth -------------------------------------------------------------
    def authed(req: Request) -> bool:
        if not password:
            return True
        return hmac.compare_digest(req.cookies.get(COOKIE, ""), _token(secret))

    def need_login(req: Request) -> Response | None:
        if authed(req):
            return None
        return RedirectResponse("login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(err: str = ""):
        body = f"""<h1>키즈카페 빈자리 감시</h1><div class="card"><form method="post" action="login">
<label>비밀번호</label><input type="password" name="password" autofocus>
{'<div class="err">비밀번호가 틀렸습니다.</div>' if err else ''}<p><button class="btn" type="submit">로그인</button></p></form></div>"""
        return page("로그인", body)

    @app.post("/login")
    def login(password_in: str = Form(alias="password")):
        if password and not hmac.compare_digest(password_in, password):
            return RedirectResponse("login?err=1", status_code=303)
        resp = RedirectResponse("./", status_code=303)
        resp.set_cookie(COOKIE, _token(secret), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return resp

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    # ---- static / pwa -----------------------------------------------------
    @app.get("/manifest.webmanifest")
    def manifest():
        return JSONResponse(MANIFEST, media_type="application/manifest+json")

    @app.get("/icon.svg")
    def icon():
        return Response(ICON_SVG, media_type="image/svg+xml")

    @app.get("/healthz")
    def healthz():
        st = service.status
        return {"ok": True, "running": st.running, "busy": st.busy, "cycles": st.cycles,
                "last_cycle_at": st.last_cycle_at, "last_error": st.last_error}

    # ---- pages ------------------------------------------------------------
    def nav(active: str) -> str:
        items = [("./", "현황"), ("targets", "대상 관리"), ("logs", "로그")]
        links = " ".join(f'<a class="btn {"" if k == active else "sec"}" href="{k}">{v}</a>' for k, v in items)
        out = '<a class="btn sec" href="logout">로그아웃</a>' if password else ""
        return f'<div class="nav">{links}{out}</div>'

    @app.get("/", response_class=HTMLResponse)
    def index(req: Request, msg: str = ""):
        if (r := need_login(req)):
            return r
        st = service.status
        tz = service.cfg.browser.timezone
        enabled = {t.key: t.enabled for t in service.cfg.targets}
        cards = "".join(
            target_card(ts.name, ts.url, ts.slots, ts.checked_at, ts.error, tz, key=ts.key,
                        enabled=enabled.get(ts.key, True))
            for ts in st.targets.values()
        ) or '<div class="card empty">감시 대상이 없습니다. "대상 관리"에서 추가하세요.</div>'
        state = "확인 중…" if st.busy else ("실행 중" if st.running else "중지")
        nxt = fmt_ts(st.next_cycle_at, tz) if st.next_cycle_at else "-"
        err = f'<div class="err">마지막 오류: {html.escape(st.last_error)}</div>' if st.last_error else ""
        note = f'<div class="ok">{html.escape(msg)}</div>' if msg else ""
        body = f"""<h1>키즈카페 빈자리 현황</h1>
<div class="sub">{state} · 마지막 확인 {fmt_ts(st.last_cycle_at, tz)} · 다음 {nxt} · 주기 {service.cfg.schedule.interval_sec // 60}분</div>
{nav("./")}{note}{err}
<form method="post" action="check" class="inline"><button class="btn" type="submit" {"disabled" if st.busy else ""}>지금 확인</button></form>
<form method="post" action="notify/test" class="inline"><button class="btn sec" type="submit">알림 테스트</button></form>
<div style="height:12px"></div>{cards}"""
        return page("키즈카페 빈자리 현황", body, refresh_sec=60 if st.busy else 300)

    @app.post("/check")
    def check(req: Request):
        if (r := need_login(req)):
            return r
        service.check_now()
        return RedirectResponse("./?msg=확인을 요청했습니다. 잠시 후 새로고침하세요.", status_code=303)

    @app.post("/notify/test")
    def notify_test(req: Request):
        if (r := need_login(req)):
            return r
        ok = all(n.safe_send("[테스트] umppa-monitor", "알림 채널 테스트", "https://umppa.seoul.go.kr/icare/")
                 for n in service.notifiers)
        return RedirectResponse(f"./?msg={'알림 전송 성공' if ok else '일부 채널 실패 (로그 확인)'}", status_code=303)

    @app.get("/targets", response_class=HTMLResponse)
    def targets(req: Request, msg: str = ""):
        if (r := need_login(req)):
            return r
        rows = []
        for t in service.cfg.targets:
            flt = []
            if t.weekdays:
                flt.append("요일 " + "".join("월화수목금토일"[w] for w in t.weekdays))
            if t.sessions:
                flt.append("회차 " + ",".join(t.sessions))
            if t.dates:
                flt.append("날짜 " + ",".join(t.dates))
            toggle = "중지" if t.enabled else "재개"
            rows.append(f"""<div class="card"><div class="row"><div><b>{html.escape(t.display_name())}</b>
<div class="muted">{t.kind.value} · {html.escape(t.id)} · {html.escape(' · '.join(flt) or '필터 없음')}</div></div>
<div><form class="inline" method="post" action="targets/toggle"><input type="hidden" name="key" value="{t.key}"><button class="btn sec" type="submit">{toggle}</button></form>
<form class="inline" method="post" action="targets/delete" onsubmit="return confirm('삭제할까요?')"><input type="hidden" name="key" value="{t.key}"><button class="btn danger" type="submit">삭제</button></form></div></div></div>""")
        wd_boxes = " ".join(
            f'<label style="display:inline-block;margin-right:8px"><input type="checkbox" name="weekdays" value="{i}" style="width:auto"> {"월화수목금토일"[i]}</label>'
            for i in range(7))
        note = f'<div class="ok">{html.escape(msg)}</div>' if msg else ""
        body = f"""<h1>감시 대상 관리</h1>{nav("targets")}{note}
{''.join(rows) or '<div class="card empty">등록된 대상이 없습니다.</div>'}
<div class="card"><h2>대상 추가</h2><form method="post" action="targets/add">
<label>종류</label><select name="kind"><option value="kidscafe">키즈카페 회차 예약</option><option value="program">프로그램 예약</option></select>
<label>ID (키즈카페: URL 의 q_fcltyId, 프로그램: q_progrmSn)</label><input name="id" required placeholder="예: YF260101 또는 8644">
<label>이름 (선택)</label><input name="name" placeholder="예: 여의도점">
<label>요일 필터 (선택)</label><div>{wd_boxes}</div>
<label>회차/시간 필터 (선택, 쉼표 구분)</label><input name="sessions" placeholder="예: 2회차, 14:00">
<div class="grid"><div><label>몇 달 앞까지</label><input name="months_ahead" type="number" value="1" min="0" max="3"></div>
<div><label>최소 잔여 인원</label><input name="min_remaining" type="number" value="1" min="1"></div></div>
<p><button class="btn" type="submit">추가</button></p></form></div>
<div class="card"><h2>확인 주기</h2><form method="post" action="schedule">
<label>주기(분, 최소 1)</label><input name="interval_min" type="number" value="{service.cfg.schedule.interval_sec // 60}" min="1">
<label>야간 중지 (예: 00:30-06:30, 비우면 없음)</label><input name="quiet" value="{html.escape(','.join(service.cfg.schedule.quiet_hours))}">
<p><button class="btn" type="submit">저장</button></p></form></div>"""
        return page("감시 대상 관리", body)

    @app.post("/targets/add")
    def targets_add(req: Request, kind: str = Form("kidscafe"), id: str = Form(...), name: str = Form(""),
                    weekdays: list[int] = Form([]), sessions: str = Form(""), months_ahead: int = Form(1),
                    min_remaining: int = Form(1)):
        if (r := need_login(req)):
            return r
        try:
            TargetKind(kind)
        except ValueError:
            return RedirectResponse("targets?msg=잘못된 종류", status_code=303)
        config_store.add_target(config_path, kind, id.strip(), name.strip(), sorted(set(weekdays)),
                                [s.strip() for s in sessions.split(",") if s.strip()], months_ahead, min_remaining)
        service.reload()
        return RedirectResponse("targets?msg=추가되었습니다", status_code=303)

    @app.post("/targets/toggle")
    def targets_toggle(req: Request, key: str = Form(...)):
        if (r := need_login(req)):
            return r
        cur = next((t.enabled for t in service.cfg.targets if t.key == key), None)
        if cur is not None:
            config_store.set_target_enabled(config_path, key, not cur)
            service.reload()
        return RedirectResponse("targets?msg=변경되었습니다", status_code=303)

    @app.post("/targets/delete")
    def targets_delete(req: Request, key: str = Form(...)):
        if (r := need_login(req)):
            return r
        config_store.remove_target(config_path, key)
        service.reload()
        return RedirectResponse("targets?msg=삭제되었습니다", status_code=303)

    @app.post("/schedule")
    def schedule(req: Request, interval_min: int = Form(5), quiet: str = Form("")):
        if (r := need_login(req)):
            return r
        config_store.set_schedule(config_path, interval_sec=max(1, interval_min) * 60,
                                  quiet_hours=[q.strip() for q in quiet.split(",") if q.strip()])
        service.reload()
        return RedirectResponse("targets?msg=저장되었습니다", status_code=303)

    @app.get("/logs", response_class=HTMLResponse)
    def logs(req: Request):
        if (r := need_login(req)):
            return r
        text = "\n".join(list(service.logs.buf)[-200:]) or "(로그 없음)"
        body = f"<h1>로그</h1>{nav('logs')}<div class='card'><pre>{html.escape(text)}</pre></div>"
        return page("로그", body, refresh_sec=30)

    @app.get("/api/status.json")
    def api_status(req: Request):
        if not authed(req):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        st = service.status
        return {
            "running": st.running, "busy": st.busy, "cycles": st.cycles, "last_cycle_at": st.last_cycle_at,
            "next_cycle_at": st.next_cycle_at, "last_error": st.last_error,
            "targets": [{"key": ts.key, "name": ts.name, "url": ts.url, "checked_at": ts.checked_at, "error": ts.error,
                         "open": [s.to_dict() for s in ts.slots if s.is_open],
                         "total": len(ts.slots)} for ts in st.targets.values()],
        }

    return app


def serve(config_path: str, host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn
    uvicorn.run(create_app(config_path), host=host, port=port, log_level="info")
