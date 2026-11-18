import pytest
from pydantic import ValidationError

from ass.production.scene_spec import SceneSpec, check_episode


def _scene(**overrides) -> dict:
    base = {
        "scene_id": "t01",
        "episode_id": "t",
        "format": "product_intro",
        "role": "problem",
        "duration_s": 15,
        "setting_en": "A counter.",
        "beats": [
            {"start_s": 0, "end_s": 5, "visual_ko": "가", "visual_en": "A"},
            {"start_s": 5, "end_s": 15, "visual_ko": "나", "visual_en": "B"},
        ],
    }
    base.update(overrides)
    return base


def test_running_example_follows_format_and_length_policy(scenes, production_spec):
    assert [s.role for s in scenes] == ["problem", "solution", "usage"]
    assert check_episode(scenes, production_spec) == []


def test_scene_longer_than_15s_is_rejected():
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(_scene(duration_s=16))


def test_beats_must_cover_scene_without_gaps():
    gap = _scene(beats=[
        {"start_s": 0, "end_s": 5, "visual_ko": "가"},
        {"start_s": 6, "end_s": 15, "visual_ko": "나"},
    ])
    with pytest.raises(ValidationError, match="5초에서 시작"):
        SceneSpec.model_validate(gap)
    short = _scene(beats=[{"start_s": 0, "end_s": 10, "visual_ko": "가"}])
    with pytest.raises(ValidationError, match="duration_s"):
        SceneSpec.model_validate(short)


def test_wrong_role_order_is_reported(scenes, production_spec):
    problems = check_episode([scenes[1], scenes[0], scenes[2]], production_spec)
    assert any("장면 역할 순서" in p for p in problems)


def test_comparison_needs_two_products(production_spec):
    roles = ["criteria", "side_by_side", "verdict"]
    one = [SceneSpec.model_validate(_scene(scene_id=f"c{i}", format="comparison", role=r,
                                           products=["moalab_gel_sunscreen"]))
           for i, r in enumerate(roles)]
    assert any("2개 이상" in p for p in check_episode(one, production_spec))
    one[1].products = ["moalab_gel_sunscreen", "haruon_cream_sunscreen"]
    assert check_episode(one, production_spec) == []


def test_caption_over_12_chars_is_reported(scenes, production_spec):
    long = [s.model_copy(deep=True) for s in scenes]
    long[0].beats[0].caption_ko = "오후만 되면 당기는 피부를 위한 해결책"
    assert any("자막" in p for p in check_episode(long, production_spec))


def test_episode_over_60s_is_reported(scenes, production_spec):
    problems = check_episode(scenes * 2, production_spec)
    assert any("상한" in p for p in problems)
