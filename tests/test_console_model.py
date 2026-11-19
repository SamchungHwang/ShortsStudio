import pytest

from ass import cli
from ass import console_model as model
from ass.guards.cost_guard import UnknownPrice
from ass.workflow import load_workflow


def test_stage_rows_show_which_commands_exist(models_config):
    rows = model.stage_rows(load_workflow(), cli.available_commands(), models_config)
    assert [r.name for r in rows] == ["소재", "대본", "제품 레퍼런스", "장면 생성", "오디오", "조립·업로드"]
    assert rows[1].commands == "script [없음] · compile [있음]"
    assert (rows[3].ready, rows[3].total) == (1, 3)
    assert rows[3].models == "Gemini Omni Flash 1.2"


def test_every_workflow_command_has_a_note():
    wf = load_workflow()
    assert set(wf.commands()) == set(wf.command_notes)


def test_episode_list_and_summary():
    assert model.list_episodes() == ["product_intro"]
    summary = model.episode_summary("product_intro")
    assert "제품 설명 · 장면 3개 · 45초 · 초안 1회 추정 $3.15 (720p)" in summary


def test_compile_is_one_run_and_free():
    assert model.build_runs("compile", "product_intro") == [["compile", "--episode", "product_intro"]]
    assert model.paid_estimate("compile", "product_intro", dry_run=False) == 0.0


def test_render_all_scenes_becomes_one_run_per_scene():
    runs = model.build_runs("render", "product_intro", model.ALL_SCENES, model.SPEC_DURATION, dry_run=True)
    assert runs == [["render", "--episode", "product_intro", "--scene", str(n), "--dry-run"] for n in (1, 2, 3)]
    assert model.paid_estimate("render", "product_intro", dry_run=True) == 0.0


def test_real_render_cost_follows_scene_and_duration():
    assert model.paid_estimate("render", "product_intro", model.ALL_SCENES, model.SPEC_DURATION, False) == 3.15
    assert model.paid_estimate("render", "product_intro", "2", "5", False) == 0.35
    assert model.build_runs("render", "product_intro", "2", "5", False) == [
        ["render", "--episode", "product_intro", "--scene", "2", "--duration", "5"]]


def test_commands_that_do_not_exist_cannot_be_run_from_console():
    with pytest.raises(ValueError, match="실행할 수 없는 명령"):
        model.build_runs("publish", "product_intro")
    with pytest.raises(ValueError, match="장면 번호"):
        model.build_runs("render", "product_intro", "9")


def test_unknown_price_is_not_hidden(monkeypatch):
    from ass.policy import load_policy

    spec = load_policy("production_spec")
    spec.data["shot"]["draft_resolution"] = "360p"
    real = model.load_policy
    monkeypatch.setattr(model, "load_policy", lambda name: spec if name == "production_spec" else real(name))
    with pytest.raises(UnknownPrice):
        model.paid_estimate("render", "product_intro", dry_run=False)


def test_preview_shows_prompt_narration_and_evidence():
    text = model.preview("product_intro", "2")
    assert "=== 장면 2: serum_s02 (solution, 15초) ===" in text
    assert "[4-10s] 묽은 젤 제형이고 향이 없다.  [자막: 묽은 젤, 무향]  (근거: serum_texture, serum_fragrance)" in text


def test_outputs_are_listed_newest_first(tmp_path):
    import os

    (tmp_path / "renders").mkdir()
    old, new = tmp_path / "renders" / "a.json", tmp_path / "b.mp4"
    old.write_text("{}")
    new.write_bytes(b"0" * 2_500_000)
    os.utime(old, (1, 1))
    (tmp_path / ".gitkeep").write_text("")
    rows = model.list_outputs(tmp_path)
    assert [r[0] for r in rows] == ["b.mp4", "renders/a.json"]
    assert rows[0][2] == "2.5MB" and rows[1][2] == "1KB"
