"""Playwright 기반 페이지 수집.

- 헤드리스 크로미움으로 대상 페이지를 열고 렌더된 HTML 을 가져온다.
- 페이지가 발생시키는 XHR/fetch 응답(.do, JSON)을 가로채 파서에 넘긴다.
- 키즈카페 달력: 이번 달 + months_ahead 만큼 '다음 달' 이동, 각 날짜 셀 클릭 시
  나타나는 회차 목록 HTML 을 수집한다.
- inspect 모드: HTML/스크린샷/네트워크 로그를 artifacts 에 저장한다.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Response, sync_playwright, TimeoutError as PWTimeout

from .config import BrowserConfig, ParserOverrides
from .models import Target, TargetKind

log = logging.getLogger(__name__)

NEXT_MONTH_TEXTS = ["다음달", "다음 달", "다음", "next", "▶", ">", "》", "〉"]
CAPTURE_URL_HINT = re.compile(r"(Resve|Cal|Progrm|Time|Slot|List|select)", re.I)


@dataclass
class NetworkRecord:
    url: str
    method: str
    status: int
    request_body: str | None
    content_type: str
    body_text: str | None
    json_obj: Any | None = None


@dataclass
class FetchResult:
    target: Target
    pages: list[tuple[str, str]] = field(default_factory=list)          # (url, html)  달력/상세 페이지
    slot_pages: list[tuple[str | None, str, str]] = field(default_factory=list)  # (date, url, html)  날짜 클릭 결과
    network: list[NetworkRecord] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def resolve_executable(cfg: BrowserConfig) -> str | None:
    if cfg.executable_path and os.path.isfile(cfg.executable_path):
        return cfg.executable_path
    # 이 저장소를 만든 실행 환경(사전 설치된 크로미움) 지원
    for cand in ["/opt/pw-browsers/chromium"] + glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None  # Playwright 기본 브라우저 사용 (playwright install chromium 필요)


class BrowserSession:
    """with 블록 안에서 브라우저를 열고 닫는다."""

    def __init__(self, cfg: BrowserConfig, allowed_hosts: list[str] | None = None):
        self.cfg = cfg
        self.allowed_hosts = [h.lower() for h in (allowed_hosts or []) + list(cfg.allowed_hosts)]
        self._pw = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        exe = resolve_executable(self.cfg)
        launch_kwargs: dict[str, Any] = {
            "headless": self.cfg.headless,
            # 불필요한 백그라운드 통신(구글 계정/업데이트 확인 등) 차단
            "args": ["--disable-background-networking", "--disable-component-update",
                     "--disable-sync", "--no-default-browser-check", "--no-first-run",
                     "--disable-features=OptimizationHints,MediaRouter,Translate"],
        }
        if exe:
            launch_kwargs["executable_path"] = exe
        self.browser = self._pw.chromium.launch(**launch_kwargs)
        ctx_kwargs: dict[str, Any] = {"locale": self.cfg.locale, "timezone_id": self.cfg.timezone}
        if self.cfg.user_agent:
            ctx_kwargs["user_agent"] = self.cfg.user_agent
        if self.cfg.storage_state and os.path.isfile(self.cfg.storage_state):
            ctx_kwargs["storage_state"] = self.cfg.storage_state
        self.context = self.browser.new_context(**ctx_kwargs)
        self.context.set_default_timeout(self.cfg.timeout_ms)
        if self.allowed_hosts:
            self.context.route("**/*", self._route)
        return self

    def _host_allowed(self, host: str) -> bool:
        host = host.lower()
        return any(host == h or host.endswith("." + h) for h in self.allowed_hosts)

    def _route(self, route, request) -> None:
        try:
            host = urlparse(request.url).hostname or ""
            if request.url.startswith(("data:", "blob:", "about:")) or self._host_allowed(host):
                route.continue_()
            else:
                route.abort()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    def __exit__(self, *exc) -> None:
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def new_page(self) -> Page:
        assert self.context is not None
        return self.context.new_page()

    def save_storage_state(self, path: str) -> None:
        assert self.context is not None
        self.context.storage_state(path=path)


def _attach_capture(page: Page, sink: list[NetworkRecord]) -> None:
    def on_response(resp: Response) -> None:
        try:
            url = resp.url
            ct = resp.headers.get("content-type", "")
            rtype = resp.request.resource_type
            if rtype not in ("xhr", "fetch", "document"):
                return
            if rtype == "document" and not CAPTURE_URL_HINT.search(url):
                return
            body: str | None = None
            jobj: Any | None = None
            try:
                body = resp.text()
            except Exception:
                body = None
            if body and ("json" in ct or body.lstrip().startswith(("{", "["))):
                try:
                    jobj = json.loads(body)
                except Exception:
                    jobj = None
            sink.append(NetworkRecord(
                url=url, method=resp.request.method, status=resp.status,
                request_body=resp.request.post_data, content_type=ct,
                body_text=body if body and len(body) < 2_000_000 else None, json_obj=jobj,
            ))
        except Exception as e:  # 캡처 실패는 감시 자체를 막지 않는다
            log.debug("capture error: %s", e)

    page.on("response", on_response)


def _settle(page: Page, ms: int = 800) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PWTimeout:
        pass
    page.wait_for_timeout(ms)


def _click_next_month(page: Page, selector: str | None) -> bool:
    if selector:
        loc = page.locator(selector).first
        if loc.count():
            loc.click()
            return True
        return False
    # 1) 흔한 클래스/타이틀
    for sel in ["a.next", "button.next", ".btn-next", ".btn_next", "[class*=next]", "[title*=다음]", "[aria-label*=다음]",
                "a[onclick*=next]", "a[onclick*=Next]", "button[onclick*=next]", "a[onclick*='+1']", "a[onclick*=Month]"]:
        loc = page.locator(sel)
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(n):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    el.click()
                    return True
            except Exception:
                continue
    # 2) 텍스트
    for txt in NEXT_MONTH_TEXTS:
        loc = page.get_by_text(txt, exact=True)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                return True
        except Exception:
            continue
    return False


def _clickable_date_elements(page: Page, selector: str | None) -> list[Any]:
    """달력에서 클릭 가능한 날짜 요소 목록 (ElementHandle)."""
    if selector:
        return page.query_selector_all(selector)
    handles = page.query_selector_all("table td a, table td button, td[onclick], [class*=day][onclick], li[data-date] a")
    return handles


def fetch_kidscafe(session: BrowserSession, target: Target, overrides: ParserOverrides,
                   artifacts_dir: str | None = None) -> FetchResult:
    result = FetchResult(target=target)
    page = session.new_page()
    _attach_capture(page, result.network)
    url = target.resolved_url()
    try:
        page.goto(url, wait_until="domcontentloaded")
        _settle(page, 1200)
        for month_idx in range(target.months_ahead + 1):
            html = page.content()
            result.pages.append((page.url, html))
            if artifacts_dir:
                p = Path(artifacts_dir) / f"{target.key.replace(':', '_')}_cal_{month_idx}.png"
                page.screenshot(path=str(p), full_page=True)
                result.screenshots.append(str(p))

            if target.click_dates:
                _collect_slot_pages(page, target, overrides, result)

            if month_idx < target.months_ahead:
                if not _click_next_month(page, overrides.next_month_selector):
                    result.errors.append("next-month control not found")
                    break
                _settle(page, 1200)
    except Exception as e:
        result.errors.append(f"{type(e).__name__}: {e}")
        log.warning("fetch_kidscafe %s failed: %s", target.key, e)
    finally:
        page.close()
    return result


def _collect_slot_pages(page: Page, target: Target, overrides: ParserOverrides, result: FetchResult) -> None:
    """각 날짜 요소를 클릭해 회차 목록 HTML 을 모은다. 페이지 이동이 일어나면 뒤로 간다."""
    from bs4 import BeautifulSoup
    from .models import normalize_date
    from .parsers.calendar import find_year_month

    base_url = page.url
    sel = overrides.calendar_cell_selector
    click_sel = f"{sel} a, {sel} button" if sel else None
    ym = find_year_month(BeautifulSoup(page.content(), "lxml"))
    count = len(_clickable_date_elements(page, click_sel))
    for i in range(count):
        handles = _clickable_date_elements(page, click_sel)
        if i >= len(handles):
            break
        el = handles[i]
        try:
            info = el.evaluate("""e => {
                const td = e.closest('td') || e.closest('li') || e.parentElement;
                const attrs = {};
                for (const n of ['data-date','data-ymd','data-day','data-dt','onclick','href','title','id']) {
                    if (e.getAttribute(n)) attrs['el:' + n] = e.getAttribute(n);
                    if (td && td.getAttribute(n)) attrs['td:' + n] = td.getAttribute(n);
                }
                const dayEl = td ? td.querySelector('em, strong, span, b, p') : null;
                return {tdText: td ? td.innerText : e.innerText, dayText: dayEl ? dayEl.innerText : '',
                        elText: e.innerText, attrs: attrs, cls: td ? (td.className || '') : ''};
            }""")
            td_text = (info.get("tdText") or "").strip()
            if not re.search(r"\d", td_text):
                continue
            if any(k in (info.get("cls") or "") for k in ("other", "prev", "next", "disabled-month", "empty", "blank")):
                continue
            if not el.is_visible():
                continue
            date_hint = None
            for v in info.get("attrs", {}).values():
                date_hint = normalize_date(str(v))
                if date_hint:
                    break
            if date_hint is None and ym:
                m = re.match(r"\s*(\d{1,2})", info.get("dayText") or td_text)
                if m and 1 <= int(m.group(1)) <= 31:
                    date_hint = f"{ym[0]:04d}-{ym[1]:02d}-{int(m.group(1)):02d}"
            before_url = page.url
            el.click()
            _settle(page, 700)
            after_url = page.url
            result.slot_pages.append((date_hint, after_url, page.content()))
            if after_url != before_url:
                page.go_back(wait_until="domcontentloaded")
                _settle(page, 800)
                if page.url != base_url and not page.url.startswith(base_url.split("?")[0]):
                    page.goto(base_url, wait_until="domcontentloaded")
                    _settle(page, 800)
            else:
                # 모달이면 닫기 시도 (다음 클릭에 영향 없도록)
                for csel in [".modal .close", ".layer .close", "button.close", "[class*=close]", "text=닫기"]:
                    try:
                        loc = page.locator(csel).first
                        if loc.count() and loc.is_visible():
                            loc.click()
                            page.wait_for_timeout(200)
                            break
                    except Exception:
                        continue
        except Exception as e:
            result.errors.append(f"click date #{i}: {type(e).__name__}: {e}")
            try:
                if page.url != base_url:
                    page.goto(base_url, wait_until="domcontentloaded")
                    _settle(page, 800)
            except Exception:
                pass


def fetch_program(session: BrowserSession, target: Target, overrides: ParserOverrides,
                  artifacts_dir: str | None = None) -> FetchResult:
    result = FetchResult(target=target)
    page = session.new_page()
    _attach_capture(page, result.network)
    try:
        page.goto(target.resolved_url(), wait_until="domcontentloaded")
        _settle(page, 1000)
        result.pages.append((page.url, page.content()))
        if artifacts_dir:
            p = Path(artifacts_dir) / f"{target.key.replace(':', '_')}_program.png"
            page.screenshot(path=str(p), full_page=True)
            result.screenshots.append(str(p))
    except Exception as e:
        result.errors.append(f"{type(e).__name__}: {e}")
        log.warning("fetch_program %s failed: %s", target.key, e)
    finally:
        page.close()
    return result


def fetch_program_list(session: BrowserSession, fclty_id: str = "") -> tuple[str, str]:
    """프로그램 목록 페이지를 열어 (url, html) 반환. 웹 앱의 프로그램 선택지 수집용."""
    from .models import BASE_URL, PROGRAM_LIST_PATH
    url = f"{BASE_URL}{PROGRAM_LIST_PATH}"
    if fclty_id:
        url += f"?q_fcltyId={fclty_id}"
    page = session.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        _settle(page, 1000)
        return page.url, page.content()
    finally:
        page.close()


def fetch_target(session: BrowserSession, target: Target, overrides: ParserOverrides,
                 artifacts_dir: str | None = None) -> FetchResult:
    if target.kind == TargetKind.KIDSCAFE:
        return fetch_kidscafe(session, target, overrides, artifacts_dir)
    return fetch_program(session, target, overrides, artifacts_dir)


def dump_fetch_result(result: FetchResult, out_dir: str | Path) -> Path:
    """inspect 용: HTML/네트워크 로그를 파일로 저장."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for i, (url, html) in enumerate(result.pages):
        (out / f"page_{i}.html").write_text(html, encoding="utf-8")
    for i, (d, url, html) in enumerate(result.slot_pages):
        (out / f"slot_{i}_{d or 'unknown'}.html").write_text(html, encoding="utf-8")
    net = [{
        "url": r.url, "method": r.method, "status": r.status, "content_type": r.content_type,
        "request_body": r.request_body, "body_preview": (r.body_text or "")[:4000],
    } for r in result.network]
    (out / "network.json").write_text(json.dumps(net, ensure_ascii=False, indent=2), encoding="utf-8")
    for i, r in enumerate(result.network):
        if r.json_obj is not None:
            (out / f"xhr_{i}.json").write_text(json.dumps(r.json_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "errors.txt").write_text("\n".join(result.errors), encoding="utf-8")
    return out


def allowed_hosts_for(targets: list[Target]) -> list[str]:
    """대상 URL 의 호스트 + 포털 도메인. 그 외 호스트로의 브라우저 요청은 차단한다."""
    hosts = {"seoul.go.kr", "umppa.seoul.go.kr", "icare.seoul.go.kr"}
    for t in targets:
        h = urlparse(t.resolved_url()).hostname
        if h:
            hosts.add(h.lower())
    return sorted(hosts)
