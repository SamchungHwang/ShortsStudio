import pytest

from ass import cli
from ass import console_model as model
from ass.guards.cost_guard import UnknownPrice
from ass.workflow import load_workflow


def test_stage_rows_show_which_commands_exist(models_config):
    rows = model.stage_rows(load_workflow(), cli.available_commands(), models_config)
    assert [r.name for r in rows] == ["소재", "대본", "제품 레퍼런스", "장면 생성", "오디오", "조립·업로드"]
    assert rows[1].commands == "script [있음] · compile [있음]"
    assert (rows[3].ready, rows[3].total) == (1, 3)
    assert rows[3].models == "Gemini Omni Flash 1.2"


def test_every_workflow_command_has_a_note():
    wf = load_workflow()
    assert set(wf.commands()) == set(wf.command_notes)


def test_episode_list_and_summary():
    assert model.list_episodes() == ["product_intro", "sunscreen_compare", "watering_plants"]
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


def test_compile_files_are_listed_in_reading_order():
    rows = model.command_files("compile", "product_intro")
    reads = [r for r in rows if r.kind == "읽음"]
    assert [r.mark for r in reads] == ["①", "①", "①", "②", "③", "④", "⑤", "⑥"]
    assert reads[0].path == "examples/moalab_skincare/episodes/product_intro/scene_01_problem.yaml"
    assert reads[0].what == "장면 1 (problem, 15초): 구간 3개의 화면, 내레이션, 자막, 근거"
    assert reads[4].path == "examples/moalab_skincare/source_briefs/aqua_serum_intro.yaml"
    assert reads[5].path == "configs/production_spec.yaml"
    assert all(r.exists for r in reads)
    writes = [r.path for r in rows if r.kind == "씀"]
    assert writes[0] == "outputs/compiled/product_intro/serum_s01.prompt.txt"
    assert writes[-1] == "outputs/compiled/product_intro/storyboard.md" and len(writes) == 7
    assert model.files_summary(rows) == "파일 8개를 읽고 7개를 쓴다"


def test_render_files_follow_scene_choice_and_never_show_key():
    rows = model.command_files("render", "product_intro", "2")
    assert [r.path for r in rows if r.mark == "①"] == [
        "examples/moalab_skincare/episodes/product_intro/scene_02_solution.yaml"]
    assert any(r.path == "configs/budget_policy.yaml" for r in rows)
    env = next(r for r in rows if r.path == ".env")
    assert "값은 어디에도 보여 주지 않는다" in env.what
    assert [r.path for r in rows if r.kind == "씀"] == [
        "outputs/renders/product_intro/serum_s02.<실행 시각>.mp4",
        "outputs/renders/product_intro/serum_s02.<실행 시각>.api_run.json"]


def test_missing_files_are_reported(tmp_path):
    (tmp_path / "episodes" / "empty").mkdir(parents=True)
    rows = model.command_files("compile", "empty", example_dir=tmp_path, root=tmp_path)
    assert rows[0].status == "없음" and rows[0].path == "episodes/empty/scene_*.yaml"
    assert "없는 파일 2개" in model.files_summary(rows)        # 장면 사양과 제품 바이블
    brief = next(r for r in rows if r.mark == "③")
    assert brief.status == "없음 (없어도 된다)"
    assert model.command_files("publish", "product_intro") == []


def test_finish_state_는_종료코드를_말로_바꾼다():
    from ass import console_model as m
    assert m.finish_state(0) == ("끝났습니다", "ok")
    assert m.finish_state(4) == ("가드가 막았습니다", "guard")
    assert m.finish_state(1) == ("실패했습니다 (종료코드 1)", "fail")
    assert m.finish_state(1, stopped=True) == ("멈췄습니다", "stop")
    assert m.finish_mark(0) == "✔" and m.finish_mark(2) == "✖"


def test_산출물_목록에는_고른_레퍼런스와_기록도_나온다(tmp_path):
    out, project = tmp_path / "outputs", tmp_path
    (out / "sheets").mkdir(parents=True)
    (out / "sheets" / "a.jpg").write_bytes(b"1")
    base = project / "assets" / "products" / "p1"
    (base / "reference").mkdir(parents=True)
    (base / "reference" / "front.jpg").write_bytes(b"2")
    (base / "reference_manifest.json").write_text("{}", encoding="utf-8")
    (base / "photos").mkdir()
    (base / "photos" / "mine.jpg").write_bytes(b"3")          # 내가 넣은 사진은 산출물이 아니다
    (project / "drafts" / "ep1").mkdir(parents=True)
    (project / "drafts" / "ep1" / "brief.yaml").write_text("title_ko: x", encoding="utf-8")   # 글 모델의 초안 (6장)
    paths = {row[0] for row in model.list_outputs(out, example_dir=project)}
    assert paths == {"sheets/a.jpg", "../assets/products/p1/reference/front.jpg",
                     "../assets/products/p1/reference_manifest.json", "../drafts/ep1/brief.yaml"}
    assert {row[0] for row in model.list_outputs(out)} == {"sheets/a.jpg"}
