"""웹앱이 쓰는 데이터(data.json)와 감시 조건(prefs) 처리 테스트."""

import json
from pathlib import Path

from umppa_monitor.cli import main
from umppa_monitor.config import load_config
from umppa_monitor.models import Slot, SlotStatus, TargetKind
from umppa_monitor.parsers.program import parse_program_list_html
from umppa_monitor.webdata import (Prefs, TargetPrefs, apply_prefs, build_snapshot, build_target_view,
                                   load_prefs, parse_prefs, save_prefs, save_webdata, session_sort_key)

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "kidscafe:YF260101"


def _cfg(tmp_path: Path, extra: str = "") -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(
        "targets:\n  - type: kidscafe\n    id: YF260101\n    name: 여의도점\n"
        "notifiers:\n  - type: console\nschedule:\n  interval_sec: 600\nstate_dir: state\n" + extra,
        encoding="utf-8")
    return p


def _slots() -> list[Slot]:
    mk = lambda d, s, st, rem: Slot(KEY, TargetKind.KIDSCAFE, d, s, st, rem)   # noqa: E731
    return [
        mk("2026-09-15", "1회차 공용", SlotStatus.OPEN, 38),
        mk("2026-09-15", "2회차 개인", SlotStatus.OPEN, 33),
        mk("2026-09-15", "3회차 개인", SlotStatus.FULL, 0),
        mk("2026-09-19", "1회차 개인", SlotStatus.FULL, 0),
        mk("2026-10-02", "1회차 공용", SlotStatus.OPEN, 5),
    ]


# --------------------------------------------------------------- 달력 데이터
def test_build_target_view_groups_by_date(tmp_path):
    target = load_config(_cfg(tmp_path)).targets[0]
    view = build_target_view(target, {"checked_at": 1_800_000_000.0,
                                      "slots": [s.to_dict() for s in _slots()]})
    assert view["key"] == KEY and view["kind"] == "kidscafe"
    # 날짜별로 묶이고 회차는 번호 순으로 정렬된다
    assert list(view["days"]) == ["2026-09-15", "2026-09-19", "2026-10-02"]
    assert [s["session"] for s in view["days"]["2026-09-15"]["slots"]] == ["1회차 공용", "2회차 개인", "3회차 개인"]
    # open 은 '열린 회차 수', seats 는 '열린 회차의 잔여 합'
    assert view["days"]["2026-09-15"]["open"] == 2
    assert view["days"]["2026-09-15"]["seats"] == 71
    assert view["days"]["2026-09-19"]["open"] == 0 and view["days"]["2026-09-19"]["seats"] == 0
    assert view["open_count"] == 3 and view["total"] == 5
    # 회차 번호가 먼저, 같은 번호면 한글 순서 ('개인' < '공용')
    assert view["sessions"] == ["1회차 개인", "1회차 공용", "2회차 개인", "3회차 개인"]


def test_session_sort_key_orders_by_round_number():
    labels = ["10회차", "2회차 개인", "1회차 공용", "상시"]
    assert sorted(labels, key=session_sort_key) == ["1회차 공용", "2회차 개인", "10회차", "상시"]


def test_save_webdata_keeps_targets_not_seen_this_cycle(tmp_path):
    save_webdata(tmp_path, {KEY: _slots()})
    save_webdata(tmp_path, {"program:8644": []})
    data = json.loads((tmp_path / "webdata.json").read_text(encoding="utf-8"))
    assert set(data["targets"]) == {KEY, "program:8644"}
    assert len(data["targets"][KEY]["slots"]) == 5


def test_webdata_records_failure_reason(tmp_path):
    """화면이 빈 채로 남지 않도록 실패 이유가 대상별로 실린다."""
    cfg = load_config(_cfg(tmp_path))
    save_webdata(tmp_path / "state", {KEY: _slots()}, {KEY: "회차 정보를 읽지 못했습니다"})
    snap = build_snapshot(cfg, tmp_path / "state", None)
    assert snap["targets"][0]["error"] == "회차 정보를 읽지 못했습니다"
    # 이유가 없으면 빈 문자열 (앱에서 falsy 로 다룬다)
    save_webdata(tmp_path / "state", {KEY: _slots()})
    assert build_snapshot(cfg, tmp_path / "state", None)["targets"][0]["error"] == ""


def test_webdata_keeps_last_slots_when_fetch_fails(tmp_path):
    """수집이 아예 실패한 대상은 직전 현황을 유지하고 이유만 덧붙인다."""
    save_webdata(tmp_path, {KEY: _slots()})
    save_webdata(tmp_path, {}, {KEY: "예약 페이지를 열지 못했습니다 (TimeoutError)"})
    entry = json.loads((tmp_path / "webdata.json").read_text(encoding="utf-8"))["targets"][KEY]
    assert len(entry["slots"]) == 5                      # 직전 슬롯 보존
    assert "열지 못했습니다" in entry["error"]


def test_build_snapshot_shape(tmp_path):
    cfg = load_config(_cfg(tmp_path))
    save_webdata(tmp_path / "state", {KEY: _slots()})
    snap = build_snapshot(cfg, tmp_path / "state", None, [{"id": "8644", "name": "오감놀이"}])
    assert snap["tz"] == "Asia/Seoul" and snap["interval_sec"] == 600
    assert snap["targets"][0]["days"]["2026-09-15"]["seats"] == 71
    assert snap["programs"][0]["id"] == "8644"
    # 설정 파일의 현재 필터가 웹 UI 초기 상태로 실린다
    assert snap["prefs"]["targets"][KEY]["min_remaining"] == 1


# ------------------------------------------------------------------- prefs
def test_parse_prefs_rejects_bad_values():
    p = parse_prefs({
        "targets": {KEY: {"weekdays": [5, 6, 9, "x", 5], "dates": ["2026-09-15", "nope"],
                          "sessions": ["1회차", "1회차", ""], "min_remaining": 0, "enabled": False}},
        "programs": ["8644", "bad-id!", "8644"],
        "updated_at": "not-a-number",
    })
    t = p.targets[KEY]
    assert t.weekdays == [5, 6]                 # 범위 밖/중복/문자 제거
    assert t.dates == ["2026-09-15"]            # 날짜 형식만
    assert t.sessions == ["1회차"]              # 중복/빈 값 제거
    assert t.min_remaining == 1                 # 최소 1 로 보정
    assert t.enabled is False
    assert p.programs == ["8644"]               # 기호 포함 id 제거, 중복 제거
    assert p.updated_at == 0.0


def test_prefs_roundtrip(tmp_path):
    path = tmp_path / "webstate" / "prefs.json"
    save_prefs(path, Prefs(updated_at=123.0, targets={KEY: TargetPrefs(weekdays=[1, 2])}, programs=["8644"]))
    back = load_prefs(path)
    assert back.updated_at == 123.0 and back.targets[KEY].weekdays == [1, 2] and back.programs == ["8644"]
    assert load_prefs(tmp_path / "missing.json") is None


def test_apply_prefs_overrides_filters_and_adds_programs(tmp_path):
    cfg = load_config(_cfg(tmp_path))
    prefs = Prefs(
        targets={KEY: TargetPrefs(weekdays=[5, 6], sessions=["2회차"], min_remaining=3, enabled=True)},
        programs=["8644"],
    )
    apply_prefs(cfg, prefs, [{"id": "8644", "name": "오감놀이"}])
    kids = next(t for t in cfg.targets if t.key == KEY)
    assert kids.weekdays == [5, 6] and kids.sessions == ["2회차"] and kids.min_remaining == 3
    # 웹에서 고른 프로그램이 별개 대상으로 추가된다 (개별 판단)
    prog = next(t for t in cfg.targets if t.key == "program:8644")
    assert prog.kind == TargetKind.PROGRAM and prog.name == "오감놀이" and prog.enabled is True


def test_apply_prefs_can_disable_a_target(tmp_path):
    cfg = load_config(_cfg(tmp_path))
    apply_prefs(cfg, Prefs(targets={KEY: TargetPrefs(enabled=False)}))
    assert next(t for t in cfg.targets if t.key == KEY).enabled is False


def test_export_uses_saved_prefs(tmp_path):
    """webstate/prefs.json 이 있으면 내보낸 data.json 에 그 조건이 실린다."""
    cfg = _cfg(tmp_path)
    save_webdata(tmp_path / "state", {KEY: _slots()})
    save_prefs(tmp_path / "webstate" / "prefs.json",
               Prefs(updated_at=99.0, targets={KEY: TargetPrefs(weekdays=[5], min_remaining=4)}))
    out = tmp_path / "site"
    assert main(["export-status", "-c", str(cfg), "--out", str(out), "--api-base", "https://x.vercel.app"]) == 0
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert data["prefs"]["targets"][KEY]["weekdays"] == [5]
    assert data["prefs"]["targets"][KEY]["min_remaining"] == 4
    # 달력은 필터와 무관하게 월 전체를 담는다
    assert set(data["targets"][0]["days"]) == {"2026-09-15", "2026-09-19", "2026-10-02"}
    conf = (out / "config.js").read_text(encoding="utf-8")
    assert "https://x.vercel.app" in conf and "./data.json" in conf


def test_export_includes_live_data_url_and_offline_assets(tmp_path):
    """앱은 자주 갱신되는 사본을 먼저 읽고, 오프라인용 서비스워커도 함께 배포된다."""
    cfg = _cfg(tmp_path)
    save_webdata(tmp_path / "state", {KEY: _slots()})
    out = tmp_path / "site"
    live = "https://raw.githubusercontent.com/o/r/webdata/data.json"
    assert main(["export-status", "-c", str(cfg), "--out", str(out), "--live-data-url", live]) == 0
    conf = json.loads((out / "config.js").read_text(encoding="utf-8")
                      .removeprefix("window.UMPPA_CONFIG=").rstrip().rstrip(";"))
    assert conf["liveDataUrl"] == live and conf["dataUrl"] == "./data.json"
    assert (out / "sw.js").exists()


# --------------------------------------------------------- 프로그램 목록 파서
def test_parse_program_list():
    html = (FIXTURES / "program_list.html").read_text(encoding="utf-8")
    progs = parse_program_list_html(html)
    by_id = {p["id"]: p for p in progs}
    assert set(by_id) == {"7001", "8512", "8644"}
    assert by_id["8644"]["name"] == "오감놀이 교실"
    assert by_id["8644"]["status"] == "접수중"
    assert by_id["8644"]["period"] == "2026.09.20 ~ 2026.09.30"
    assert by_id["8644"]["url"].endswith("q_progrmSn=8644")
    # 자바스크립트 호출로만 상세를 여는 행도 잡는다
    assert by_id["8512"]["name"] == "북아트 원데이 클래스" and by_id["8512"]["status"] == "마감"
    # 페이지 번호 링크(?page=2, ?page=3)는 프로그램으로 잡히지 않는다
    assert "2" not in by_id and "3" not in by_id
