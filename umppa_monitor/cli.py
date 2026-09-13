"""CLI 진입점.

  umppa-monitor run        -c config.yaml     지속 감시
  umppa-monitor once       -c config.yaml     1회 감시 (cron/GitHub Actions 용)
  umppa-monitor inspect    -c config.yaml     페이지 구조 진단 (HTML/스크린샷/XHR 저장)
  umppa-monitor parse-file <html>             저장된 HTML 로 파서 결과 확인
  umppa-monitor test-notify -c config.yaml    알림 채널 테스트
  umppa-monitor login      -c config.yaml     (headed) 로그인 후 쿠키 저장
  umppa-monitor show-state -c config.yaml     저장된 스냅샷 출력
  umppa-monitor serve      -c config.yaml     모바일 웹 대시보드 + 감시 루프 (--port)
  umppa-monitor export-status -c config.yaml --out site   정적 상태 페이지 생성 (GitHub Pages 용)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .config import AppConfig, load_config
from .models import Target, TargetKind


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _load(args) -> AppConfig:
    cfg = load_config(args.config)
    _setup_logging(args.log_level or cfg.log_level)
    return cfg


def cmd_run(args) -> int:
    from .notify.factory import build_notifiers
    from .scheduler import run_loop
    cfg = _load(args)
    run_loop(cfg, build_notifiers(cfg.notifiers), once=False)
    return 0


def cmd_once(args) -> int:
    from .notify.factory import build_notifiers
    from .scheduler import run_loop
    cfg = _load(args)
    run_loop(cfg, build_notifiers(cfg.notifiers), once=True)
    return 0


def cmd_inspect(args) -> int:
    from .browser import BrowserSession, allowed_hosts_for, dump_fetch_result, fetch_target
    from .scanner import slots_from_result
    cfg = _load(args)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = Path(cfg.artifacts_dir) / "inspect" / ts
    base.mkdir(parents=True, exist_ok=True)
    targets = [t for t in cfg.targets if t.enabled]
    if args.target:
        targets = [t for t in cfg.targets if t.id == args.target or t.key == args.target]
    with BrowserSession(cfg.browser, allowed_hosts_for(targets)) as session:
        for t in targets:
            out = base / t.key.replace(":", "_")
            out.mkdir(parents=True, exist_ok=True)
            res = fetch_target(session, t, cfg.parser, artifacts_dir=str(out))
            dump_fetch_result(res, out)
            slots = slots_from_result(res, cfg.parser)
            (out / "parsed_slots.json").write_text(
                json.dumps([s.to_dict() for s in slots], ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\n=== {t.display_name()} ===")
            print(f"pages: {len(res.pages)}, slot pages: {len(res.slot_pages)}, xhr: {len(res.network)}, errors: {len(res.errors)}")
            for e in res.errors[:10]:
                print("  ! " + e)
            print(f"parsed slots: {len(slots)}")
            for s in slots[:40]:
                print(f"  {s.date} | {s.session:<22} | {s.status.value:<7} | rem={s.remaining} cap={s.capacity} | {s.raw[:60]}")
            print(f"저장 위치: {out}")
    print("\n위 폴더의 page_*.html / slot_*.html / network.json / xhr_*.json 을 확인해 config.parser 를 조정하세요.")
    return 0


def cmd_parse_file(args) -> int:
    from .config import ParserOverrides
    from .parsers.calendar import parse_calendar_html, parse_slot_list_html
    from .parsers.program import parse_program_html
    _setup_logging(args.log_level or "INFO")
    html = Path(args.file).read_text(encoding="utf-8", errors="replace")
    t = Target(kind=TargetKind(args.type), id=args.id or "X")
    ov = ParserOverrides()
    if args.type == "program":
        slots = parse_program_html(html, t, ov, args.file)
    elif args.mode == "slots":
        slots = parse_slot_list_html(html, t, args.date, ov, args.file)
    else:
        slots = parse_calendar_html(html, t, ov, args.file)
    for s in slots:
        print(f"{s.date} | {s.session:<22} | {s.status.value:<7} | rem={s.remaining} cap={s.capacity} | {s.raw[:70]}")
    print(f"total {len(slots)}")
    return 0


def cmd_test_notify(args) -> int:
    from .notify.factory import build_notifiers
    cfg = _load(args)
    ok = True
    for n in build_notifiers(cfg.notifiers):
        r = n.safe_send("[테스트] umppa-monitor", "알림 채널 테스트 메시지입니다.", "https://umppa.seoul.go.kr/icare/")
        print(f"{n.name}: {'OK' if r else 'FAILED'}")
        ok &= r
    return 0 if ok else 1


def cmd_login(args) -> int:
    from .browser import BrowserSession
    cfg = _load(args)
    cfg.browser.headless = False
    out = cfg.browser.storage_state or "storage_state.json"
    with BrowserSession(cfg.browser) as session:
        page = session.new_page()
        page.goto("https://umppa.seoul.go.kr/icare/", wait_until="domcontentloaded")
        print("브라우저에서 로그인한 뒤, 이 터미널에서 Enter 를 누르세요...")
        input()
        session.save_storage_state(out)
    print(f"저장됨: {out} (config.browser.storage_state 에 지정)")
    return 0


def cmd_show_state(args) -> int:
    from .state import StateStore
    cfg = _load(args)
    store = StateStore(cfg.state_dir)
    for t in cfg.targets:
        snap = store.load(t.key)
        print(f"=== {t.display_name()} ===")
        if not snap:
            print("  (없음)")
            continue
        print(f"  taken_at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snap.taken_at))}")
        for s in sorted(snap.slots.values(), key=lambda x: (x.date or "", x.session)):
            print(f"  {s.date} | {s.session:<22} | {s.status.value:<7} | rem={s.remaining}")
    return 0


def cmd_serve(args) -> int:
    from .web import serve
    cfg = _load(args)
    port = int(args.port or os.environ.get("PORT", 8000))
    serve(args.config, host=args.host, port=port)
    return 0


def cmd_export_status(args) -> int:
    """state/ 스냅샷을 읽어 정적 상태 페이지(index.html, status.json, manifest, icon)를 생성."""
    from .render_html import ICON_SVG, MANIFEST, static_status_page, status_json
    from .state import StateStore
    cfg = _load(args)
    store = StateStore(cfg.state_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    items = []
    payload = []
    for t in cfg.targets:
        if not t.enabled:
            continue
        snap = store.load(t.key)
        slots = sorted(snap.slots.values(), key=lambda s: (s.date or "", s.session)) if snap else []
        items.append((t.display_name(), t.resolved_url(), slots, snap.taken_at if snap else None))
        payload.append({"key": t.key, "name": t.display_name(), "url": t.resolved_url(),
                        "checked_at": snap.taken_at if snap else None,
                        "open": [s.to_dict() for s in slots if s.is_open], "total": len(slots)})
    now = time.time()
    (out / "index.html").write_text(static_status_page(items, cfg.browser.timezone, now, args.source_url),
                                    encoding="utf-8")
    (out / "status.json").write_text(status_json(payload, now), encoding="utf-8")
    (out / "manifest.webmanifest").write_text(json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8")
    (out / "icon.svg").write_text(ICON_SVG, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"exported {len(items)} targets -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="umppa-monitor", description="서울형 키즈카페 빈자리 감시")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-c", "--config", default="config.yaml")
        sp.add_argument("--log-level", default=None)

    for name, fn in [("run", cmd_run), ("once", cmd_once), ("test-notify", cmd_test_notify),
                     ("login", cmd_login), ("show-state", cmd_show_state)]:
        sp = sub.add_parser(name)
        common(sp)
        sp.set_defaults(func=fn)

    sp = sub.add_parser("inspect", help="페이지 구조 진단")
    common(sp)
    sp.add_argument("--target", help="특정 target id 만")
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("serve", help="웹 대시보드 실행")
    common(sp)
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("export-status", help="정적 상태 페이지 생성")
    common(sp)
    sp.add_argument("--out", default="site")
    sp.add_argument("--source-url", default=None, help="페이지 하단에 표시할 저장소/Actions 링크")
    sp.set_defaults(func=cmd_export_status)

    sp = sub.add_parser("parse-file", help="저장된 HTML 파싱 테스트")
    sp.add_argument("file")
    sp.add_argument("--type", choices=["kidscafe", "program"], default="kidscafe")
    sp.add_argument("--mode", choices=["calendar", "slots"], default="calendar")
    sp.add_argument("--date", default=None)
    sp.add_argument("--id", default=None)
    sp.add_argument("--log-level", default=None)
    sp.set_defaults(func=cmd_parse_file)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # `| head` 등 파이프 종료 시 조용히 종료
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
