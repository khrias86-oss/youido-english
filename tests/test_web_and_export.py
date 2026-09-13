import json
from pathlib import Path

from fastapi.testclient import TestClient

from umppa_monitor import config_store
from umppa_monitor.cli import main
from umppa_monitor.models import Slot, SlotStatus, TargetKind
from umppa_monitor.state import Snapshot, StateStore
from umppa_monitor.web import create_app


def _cfg(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(
        "targets:\n  - type: kidscafe\n    id: YF260101\n    name: 여의도점\n    weekdays: [5, 6]\n"
        "notifiers:\n  - type: console\nschedule:\n  interval_sec: 300\nstate_dir: state\n",
        encoding="utf-8")
    return p


def _seed_state(tmp_path: Path):
    store = StateStore(tmp_path / "state")
    slots = [
        Slot("kidscafe:YF260101", TargetKind.KIDSCAFE, "2026-09-19", "2회차 11:00~12:50", SlotStatus.OPEN, 2, 20),
        Slot("kidscafe:YF260101", TargetKind.KIDSCAFE, "2026-09-19", "1회차 09:00~10:50", SlotStatus.FULL, 0, 20),
    ]
    store.save("kidscafe:YF260101", Snapshot(taken_at=1_800_000_000.0, slots={s.key: s for s in slots}))


def test_export_status(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    _seed_state(tmp_path)
    out = tmp_path / "site"
    assert main(["export-status", "-c", str(cfg), "--out", str(out), "--source-url", "https://example.com/x"]) == 0
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "여의도점" in html and "1건 가능" in html and "2회차 11:00~12:50" in html and "viewport" in html
    data = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert data["targets"][0]["total"] == 2 and len(data["targets"][0]["open"]) == 1
    assert (out / "manifest.webmanifest").exists() and (out / ".nojekyll").exists()


def test_web_no_password(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_state(tmp_path)
    app = create_app(str(cfg), start_monitor=False)
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and "여의도점" in r.text and "1건 가능" in r.text
    r = c.get("/api/status.json")
    assert r.status_code == 200 and r.json()["targets"][0]["total"] == 2
    assert c.get("/healthz").json()["ok"] is True
    assert c.get("/manifest.webmanifest").status_code == 200

    # 대상 추가/중지/삭제가 config.yaml 에 반영되고 서비스가 reload 된다
    r = c.post("/targets/add", data={"kind": "program", "id": "8644", "name": "공예", "weekdays": ["5"], "sessions": "1회차"},
               follow_redirects=False)
    assert r.status_code == 303
    raw = config_store.read_raw(cfg)
    assert any(t["id"] == "8644" and t.get("weekdays") == [5] and t.get("sessions") == ["1회차"] for t in raw["targets"])
    assert any(t.key == "program:8644" for t in app.state.service.cfg.targets)
    c.post("/targets/toggle", data={"key": "program:8644"}, follow_redirects=False)
    assert next(t for t in app.state.service.cfg.targets if t.key == "program:8644").enabled is False
    c.post("/targets/delete", data={"key": "program:8644"}, follow_redirects=False)
    assert all(t.key != "program:8644" for t in app.state.service.cfg.targets)
    c.post("/schedule", data={"interval_min": "3", "quiet": "00:00-06:00"}, follow_redirects=False)
    assert app.state.service.cfg.schedule.interval_sec == 180
    assert app.state.service.cfg.schedule.quiet_hours == ["00:00-06:00"]
    assert c.get("/logs").status_code == 200
    assert c.get("/targets").status_code == 200


def test_web_password(tmp_path, monkeypatch):
    monkeypatch.setenv("UMPPA_WEB_PASSWORD", "secret123")
    cfg = _cfg(tmp_path)
    app = create_app(str(cfg), start_monitor=False)
    c = TestClient(app)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "login"
    assert c.get("/api/status.json").status_code == 401
    r = c.post("/login", data={"password": "wrong"}, follow_redirects=False)
    assert "err=1" in r.headers["location"]
    r = c.post("/login", data={"password": "secret123"}, follow_redirects=False)
    assert r.status_code == 303 and "umppa_session" in r.cookies
    assert c.get("/").status_code == 200
    assert c.get("/api/status.json").status_code == 200
    # 로그인 없이도 healthz/manifest 는 열림 (헬스체크·PWA 용)
    c2 = TestClient(app)
    assert c2.get("/healthz").status_code == 200


def test_config_store_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    config_store.add_target(cfg, "kidscafe", "AB1", "a", [0, 6], [], 2, 3)
    raw = config_store.read_raw(cfg)
    t = next(t for t in raw["targets"] if t["id"] == "AB1")
    assert t["months_ahead"] == 2 and t["min_remaining"] == 3 and t["weekdays"] == [0, 6]
    config_store.add_target(cfg, "kidscafe", "AB1", "renamed")     # 중복 추가는 갱신
    assert sum(1 for t in config_store.read_raw(cfg)["targets"] if t["id"] == "AB1") == 1
    assert config_store.set_target_enabled(cfg, "kidscafe:AB1", False)
    assert config_store.remove_target(cfg, "kidscafe:AB1")
    assert not config_store.remove_target(cfg, "kidscafe:AB1")
