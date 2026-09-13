"""로컬 mock 사이트로 Playwright 수집 흐름(달력 → 날짜 클릭 → 회차 모달 → 다음달, XHR 캡처)을 검증한다."""
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from umppa_monitor.browser import BrowserSession, allowed_hosts_for, fetch_target, resolve_executable
from umppa_monitor.config import BrowserConfig, ParserOverrides
from umppa_monitor.models import SlotStatus, Target, TargetKind
from umppa_monitor.scanner import slots_from_result

MOCK = Path(__file__).parent / "mocksite"


@pytest.fixture(scope="module")
def server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(MOCK))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def _browser_available() -> bool:
    if resolve_executable(BrowserConfig()):
        return True
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _browser_available(), reason="chromium not available")
def test_kidscafe_flow(server, tmp_path):
    t = Target(kind=TargetKind.KIDSCAFE, id="MOCK", url=f"{server}/cal.html", months_ahead=1, click_dates=True)
    with BrowserSession(BrowserConfig(timeout_ms=15000), allowed_hosts_for([t])) as s:
        res = fetch_target(s, t, ParserOverrides(), artifacts_dir=str(tmp_path))
    assert not res.errors, res.errors
    assert len(res.pages) == 2                       # 9월, 10월
    assert len(res.slot_pages) == 4                  # 19, 20, 26, 10/3
    assert any("times.json" in r.url for r in res.network)
    slots = slots_from_result(res, ParserOverrides())
    by = {(x.date, x.session): x for x in slots}
    assert by[("2026-09-19", "1회차 09:00~10:50")].status == SlotStatus.FULL
    s2 = by[("2026-09-19", "2회차 11:00~12:50")]
    assert s2.status == SlotStatus.OPEN and s2.remaining == 2 and s2.capacity == 20
    assert by[("2026-09-20", "2회차 11:00~12:50")].status == SlotStatus.FULL
    assert by[("2026-09-26", "1회차 09:00~10:50")].remaining == 15
    assert by[("2026-10-03", "2회차 11:00~12:50")].remaining == 1
    assert by[("2026-09-01", "day")].status == SlotStatus.CLOSED   # 휴관
    assert by[("2026-09-02", "day")].status == SlotStatus.FULL     # 예약마감
    # XHR JSON 도 병합됨
    assert by[("2026-09-27", "1회차 09:00~10:50")].remaining == 3
    assert (tmp_path / "kidscafe_MOCK_cal_0.png").exists()


@pytest.mark.skipif(not _browser_available(), reason="chromium not available")
def test_program_flow(server):
    t = Target(kind=TargetKind.PROGRAM, id="MOCKP", url=f"{server}/program.html")
    with BrowserSession(BrowserConfig(timeout_ms=15000), allowed_hosts_for([t])) as s:
        res = fetch_target(s, t, ParserOverrides())
    slots = slots_from_result(res, ParserOverrides())
    assert len(slots) == 1
    assert slots[0].status == SlotStatus.OPEN and slots[0].remaining == 2 and slots[0].date == "2026-10-03"


def test_allowed_hosts_for():
    t = Target(kind=TargetKind.KIDSCAFE, id="YF260101")
    hosts = allowed_hosts_for([t, Target(kind=TargetKind.PROGRAM, id="1", url="http://127.0.0.1:1/p.html")])
    assert "umppa.seoul.go.kr" in hosts and "127.0.0.1" in hosts
