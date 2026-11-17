import pytest

from acs.production.scene_compiler import CompileError, compile_scene


def test_compiles_running_example(scenes, bible, production_spec):
    compiled = compile_scene(scenes[0], bible, production_spec)
    p = compiled.prompt
    assert p.startswith("Vertical 9:16 video, 15 seconds")
    assert "[0-3s]" in p and "[9-15s]" in p
    assert "cream tabby cat" in p                       # 캐릭터 바이블의 외형이 들어간다
    assert 'Momo says in Korean (sleepy deadpan): "월요 회의 시작한다.' in p
    assert p.rstrip().splitlines()[-1].startswith("Constraints: ")   # 제외 지시는 본문 끝에 자연어로
    assert len(compiled.prompt_sha256) == 64


def test_compile_is_deterministic(scenes, bible, production_spec):
    a = compile_scene(scenes[1], bible, production_spec)
    b = compile_scene(scenes[1], bible, production_spec)
    assert a.prompt_sha256 == b.prompt_sha256


def test_interval_notation_can_be_turned_off(scenes, bible, production_spec):
    spec = {**production_spec, "prompt": {"language": "en", "interval_notation": False}}
    assert "[0-" not in compile_scene(scenes[0], bible, spec).prompt


def test_missing_english_action_blocks_compile(scenes, bible, production_spec):
    scene = scenes[0].model_copy(deep=True)
    scene.beats[1].action_en = None
    with pytest.raises(CompileError, match="action_en"):
        compile_scene(scene, bible, production_spec)


def test_banned_term_in_script_blocks_compile(scenes, bible, production_spec):
    scene = scenes[0].model_copy(deep=True)
    scene.beats[0].action_ko = "단추가 갇힌 채로 운다"
    with pytest.raises(CompileError, match="대본 단계") as exc:
        compile_scene(scene, bible, production_spec)
    assert exc.value.violations[0].term == "갇힌"


def test_banned_term_from_exclusions_blocks_at_compile_stage(scenes, bible, production_spec):
    scene = scenes[0].model_copy(deep=True)
    scene.exclusions_en = ["No injured animals"]        # 제외 지시에도 금지어를 쓰지 않는다
    with pytest.raises(CompileError, match="컴파일 단계"):
        compile_scene(scene, bible, production_spec)


def test_unknown_character_is_an_error(scenes, bible, production_spec):
    scene = scenes[0].model_copy(deep=True)
    scene.characters = ["momo", "danchu", "nabi"]
    with pytest.raises(KeyError, match="nabi"):
        compile_scene(scene, bible, production_spec)
