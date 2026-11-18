import pytest

from ass.production.scene_compiler import CompileError, compile_scene


def test_compiles_running_example_in_tts_mode(scenes, bible, production_spec):
    compiled = compile_scene(scenes[1], bible, production_spec)
    p = compiled.prompt
    assert p.startswith("Vertical 9:16 video, 15 seconds")
    assert "[0-4s]" in p and "[10-15s]" in p
    assert "frosted glass dropper bottle" in p            # 제품 바이블의 외형이 들어간다
    assert "묽은 젤" not in p                               # tts 모드: 내레이션은 프롬프트에 넣지 않는다
    last = p.rstrip().splitlines()[-1]
    assert last.startswith("Constraints: ") and "No speech, narration or voice-over" in last
    assert [n.text for n in compiled.narration][1] == "묽은 젤 제형이고 향이 없다."
    assert compiled.narration[1].evidence == ["serum_texture", "serum_fragrance"]
    assert compiled.needs_human_approval is False


def test_in_video_mode_puts_narration_in_prompt(scenes, bible, production_spec):
    spec = {**production_spec, "narration": {"mode": "in_video", "language": "ko"}}
    p = compile_scene(scenes[1], bible, spec).prompt
    assert 'narrator says in Korean, calm and clear: "묽은 젤 제형이고 향이 없다."' in p
    assert "No speech" not in p


def test_compile_is_deterministic(scenes, bible, production_spec):
    a = compile_scene(scenes[2], bible, production_spec)
    b = compile_scene(scenes[2], bible, production_spec)
    assert a.prompt_sha256 == b.prompt_sha256 and len(a.prompt_sha256) == 64


def test_missing_english_visual_blocks_compile(scenes, bible, production_spec):
    scene = scenes[0].model_copy(deep=True)
    scene.beats[1].visual_en = None
    with pytest.raises(CompileError, match="visual_en"):
        compile_scene(scene, bible, production_spec)


def test_claim_without_fact_in_bible_blocks_compile(scenes, bible, production_spec):
    scene = scenes[1].model_copy(deep=True)
    scene.beats[1].evidence = ["serum_absorbs_in_3_seconds"]
    with pytest.raises(CompileError, match="product_bible 에 없는 근거"):
        compile_scene(scene, bible, production_spec)


def test_banned_claim_in_narration_blocks_at_script_stage(scenes, bible, production_spec):
    scene = scenes[1].model_copy(deep=True)
    scene.beats[1].narration_ko = "피부 재생에 최고다."
    with pytest.raises(CompileError, match="대본 단계") as exc:
        compile_scene(scene, bible, production_spec)
    assert {v.category for v in exc.value.violations} == {"medical_claim", "absolute_claim"}


def test_banned_term_from_exclusions_blocks_at_compile_stage(scenes, bible, production_spec):
    scene = scenes[0].model_copy(deep=True)
    scene.exclusions_en = ["No fake products"]
    with pytest.raises(CompileError, match="컴파일 단계"):
        compile_scene(scene, bible, production_spec)


def test_competitor_product_needs_human_approval(scenes, bible, production_spec):
    scene = scenes[1].model_copy(deep=True)
    scene.products = ["moalab_gel_sunscreen", "haruon_cream_sunscreen"]
    for beat in scene.beats:
        beat.evidence = []
    compiled = compile_scene(scene, bible, production_spec)
    assert compiled.needs_human_approval is True
    assert "HARUON Cream Sunscreen" in compiled.prompt


def test_unknown_product_is_an_error(scenes, bible, production_spec):
    scene = scenes[1].model_copy(deep=True)
    scene.products = ["no_such_product"]
    with pytest.raises(KeyError, match="no_such_product"):
        compile_scene(scene, bible, production_spec)
