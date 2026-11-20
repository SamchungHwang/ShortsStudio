import json

import pytest

from ass import cli


@pytest.fixture(autouse=True)
def _outputs_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path)
    monkeypatch.delenv("ASS_RUN_BUDGET_USD", raising=False)
    return tmp_path


def test_compile_writes_prompts_and_reports_cost(tmp_path, capsys):
    assert cli.main(["compile"]) == 0
    out = capsys.readouterr().out
    assert "초안 1회 추정 비용 $3.15" in out
    files = sorted(p.name for p in (tmp_path / "compiled" / "product_intro").iterdir())
    assert files == ["serum_s01.compiled.json", "serum_s01.prompt.txt", "serum_s02.compiled.json",
                     "serum_s02.prompt.txt", "serum_s03.compiled.json", "serum_s03.prompt.txt", "storyboard.md"]
    board = (tmp_path / "compiled" / "product_intro" / "storyboard.md").read_text(encoding="utf-8")
    assert board.startswith("# 장면 설계표 — 오후에 당기는 피부, 수분 세럼 하나로")
    assert "- 약속: 수분 세럼이 어떤 제형이고 어떻게 쓰는지 45초 안에 알려 준다" in board


def test_render_dry_run_records_without_calling(tmp_path, capsys):
    assert cli.main(["render", "--scene", "2", "--dry-run"]) == 0
    records = list((tmp_path / "renders" / "product_intro").glob("serum_s02.*.api_run.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["status"] == "dry_run"
    assert record["estimated_cost_usd"] == 1.05
    assert set(record["policy_hashes"]) == {"production_spec", "models", "budget_policy"}
    assert record["request"]["response_format"]["duration"] == "15s"


def test_render_stops_when_over_run_budget(monkeypatch):
    from ass.guards.cost_guard import BudgetExceeded

    monkeypatch.setenv("ASS_RUN_BUDGET_USD", "0.50")
    with pytest.raises(BudgetExceeded):
        cli.main(["render", "--dry-run"])


def test_render_without_key_does_not_call(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_setup", lambda: None)   # .env 를 읽지 않게
    assert cli.main(["render"]) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().out


def test_unknown_episode_is_an_error():
    with pytest.raises(SystemExit, match="장면 사양이 없다"):
        cli.main(["compile", "--episode", "no_such_episode"])
