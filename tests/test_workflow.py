from ass import cli
from ass.workflow import check_workflow, load_workflow, render_markdown, render_stack


def test_workflow_has_six_stages_in_book_order():
    wf = load_workflow()
    assert [s.name_ko for s in wf.stages] == ["소재", "대본", "제품 레퍼런스", "장면 생성", "오디오", "조립·업로드"]


def test_workflow_is_self_consistent(models_config):
    assert check_workflow(load_workflow(), models_config) == []


def test_missing_upstream_output_is_reported(models_config):
    wf = load_workflow()
    wf.stages[3].inputs.append("스토리보드")
    assert any("스토리보드" in p for p in check_workflow(wf, models_config))


def test_map_marks_only_registered_commands_as_available(models_config):
    available = cli.available_commands()
    assert {"compile", "render", "map", "stack"} <= available
    md = render_markdown(load_workflow(), available, models_config)
    assert "`ass compile` (있음)" in md and "`ass publish` (없음)" in md


def test_stack_separates_confirmed_from_unverified(models_config):
    text = render_stack(models_config)
    assert "[확인]   720p 초당 $0.07" in text
    assert "[미확인] 편집 호출의 청구액 (E04)" in text
    assert "모델 ID  lyria-3.5" in text
    assert "모델 ID  미확인" in text          # 텍스트 모델


def test_map_command_writes_doc(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    assert cli.main(["map", "--write"]) == 0
    assert (tmp_path / "docs" / "workflow_map.md").read_text(encoding="utf-8").startswith("# ASS 공정 지도")
    assert "명령 12개 중 4개가 있다" in capsys.readouterr().out


def test_guard_block_is_reported_not_crashed(monkeypatch, capsys):
    from ass.production import scene_spec

    original = scene_spec.load_scene

    def tampered(path):
        scene = original(path)
        if scene.scene_id == "serum_s02":
            scene.beats[1].narration_ko = "피부 재생에 최고다."
        return scene

    monkeypatch.setattr(cli, "load_scene", tampered)
    monkeypatch.setattr(cli, "OUTPUT_DIR", __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    assert cli.main(["compile"]) == 4
    assert "[막힘] 대본 단계 제품 표현 가드 위반" in capsys.readouterr().out
