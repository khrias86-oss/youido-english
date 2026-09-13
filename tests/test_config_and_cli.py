import os
from pathlib import Path

from umppa_monitor.cli import main
from umppa_monitor.config import load_config
from umppa_monitor.models import TargetKind


def test_load_example_config(monkeypatch):
    cfg = load_config(Path(__file__).parent.parent / "config.example.yaml")
    assert cfg.targets[0].kind == TargetKind.KIDSCAFE and cfg.targets[0].id == "YF260101"
    assert cfg.targets[0].resolved_url().endswith("BD_selectKidsCafeResveCal.do?q_fcltyId=YF260101")
    assert cfg.targets[1].kind == TargetKind.PROGRAM and not cfg.targets[1].enabled
    assert cfg.targets[1].resolved_url().endswith("BD_selectKidsCafeProgrm.do?q_progrmSn=8644")
    assert cfg.notifiers[0].type == "console"
    assert cfg.schedule.interval_sec == 300


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_TOKEN", "abc")
    p = tmp_path / "c.yaml"
    p.write_text("targets:\n  - type: kidscafe\n    id: A\nnotifiers:\n  - type: telegram\n    token: ${TG_TOKEN}\n    chat_id: 1\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.notifiers[0].options["token"] == "abc"
    assert cfg.state_dir == str(tmp_path / "state")          # 설정 파일 기준 상대경로


def test_cli_parse_file(capsys):
    fx = Path(__file__).parent / "fixtures" / "slot_list.html"
    assert main(["parse-file", str(fx), "--mode", "slots", "--date", "2026-09-20"]) == 0
    out = capsys.readouterr().out
    assert "4회차 16:00~17:50" in out and "total 4" in out


def test_cli_test_notify_console(tmp_path, capsys):
    p = tmp_path / "c.yaml"
    p.write_text("targets:\n  - type: kidscafe\n    id: A\nnotifiers:\n  - type: console\n", encoding="utf-8")
    assert main(["test-notify", "-c", str(p)]) == 0
    assert "console: OK" in capsys.readouterr().out
