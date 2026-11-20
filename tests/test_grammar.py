from ass.production.grammar import check_grammar, storyboard_markdown


def test_running_example_follows_the_grammar(scenes, production_spec):
    assert check_grammar(scenes, production_spec) == []


def test_slow_or_silent_hook_is_noted(scenes, production_spec):
    s = [x.model_copy(deep=True) for x in scenes]
    s[0].beats[0].narration_ko = None
    s[0].beats[0].caption_ko = None
    assert any(n.startswith("[훅] 첫 구간에") for n in check_grammar(s, production_spec))
    s = [x.model_copy(deep=True) for x in scenes]
    s[0].beats[0].end_s = 6
    s[0].beats[1].start_s = 6
    assert any("첫 구간이 6초" in n for n in check_grammar(s, production_spec))


def test_solution_scene_without_evidence_is_noted(scenes, production_spec):
    s = [x.model_copy(deep=True) for x in scenes]
    for beat in s[1].beats:
        beat.evidence = []
    assert check_grammar(s, production_spec) == ["[근거] serum_s02(solution) 에 근거가 붙은 구간이 없다"]


def test_missing_closing_line_is_noted(scenes, production_spec):
    s = [x.model_copy(deep=True) for x in scenes]
    s[2].beats[-1].narration_ko = None
    s[2].beats[-1].caption_ko = None
    assert any(n.startswith("[다음 행동]") for n in check_grammar(s, production_spec))


def test_narration_too_long_for_its_beat_is_noted(scenes, production_spec):
    s = [x.model_copy(deep=True) for x in scenes]
    s[0].beats[0].narration_ko = "오후만 되면 피부가 당기고 화장이 들뜨고 거울을 볼 때마다 신경이 쓰인다면"
    notes = check_grammar(s, production_spec)
    assert len(notes) == 1 and "최대 21자" in notes[0] and notes[0].startswith("[읽는 속도] serum_s01.beats[0]")


def test_storyboard_is_built_from_scene_specs(scenes, production_spec):
    md = storyboard_markdown(scenes, production_spec, title="수분 세럼 소개", promise="약속 한 줄")
    assert "- 형식: 제품 설명 (문제 → 해결 → 사용법)" in md
    assert "- 길이: 15 + 15 + 15 = 45초" in md and "- 약속: 약속 한 줄" in md
    assert "## 장면 2 · 해결 (15초) — 제품: moalab_aqua_serum" in md
    assert "| 4~10초 | 스포이트를 들어 올리자 묽은 젤 한 방울이 천천히 떨어진다. | 묽은 젤 제형이고 향이 없다. | 묽은 젤, 무향 | serum_texture, serum_fragrance |" in md
    assert md.rstrip().endswith("- 주의 없음")
