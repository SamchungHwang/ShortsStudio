import pytest
from pydantic import ValidationError

from acs.production.scene_spec import SceneSpec, check_episode


def _scene(**overrides) -> dict:
    base = {
        "scene_id": "t01",
        "episode_id": "t",
        "role": "setup",
        "duration_s": 15,
        "characters": ["momo"],
        "setting_en": "A tiny office.",
        "beats": [
            {"start_s": 0, "end_s": 5, "action_ko": "가", "action_en": "A"},
            {"start_s": 5, "end_s": 15, "action_ko": "나", "action_en": "B"},
        ],
    }
    base.update(overrides)
    return base


def test_running_example_follows_length_policy(scenes, production_spec):
    assert [s.role for s in scenes] == ["setup", "escalation", "punchline"]
    assert check_episode(scenes, production_spec) == []


def test_scene_longer_than_15s_is_rejected():
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(_scene(duration_s=16))


def test_beats_must_cover_scene_without_gaps():
    gap = _scene(beats=[
        {"start_s": 0, "end_s": 5, "action_ko": "가"},
        {"start_s": 6, "end_s": 15, "action_ko": "나"},
    ])
    with pytest.raises(ValidationError, match="5초에서 시작"):
        SceneSpec.model_validate(gap)
    short = _scene(beats=[{"start_s": 0, "end_s": 10, "action_ko": "가"}])
    with pytest.raises(ValidationError, match="duration_s"):
        SceneSpec.model_validate(short)


def test_speaker_must_be_in_scene():
    bad = _scene(beats=[
        {"start_s": 0, "end_s": 15, "action_ko": "가",
         "dialogue": {"speaker": "toto", "text": "평화"}},
    ])
    with pytest.raises(ValidationError, match="toto"):
        SceneSpec.model_validate(bad)


def test_episode_over_60s_is_reported(scenes, production_spec):
    problems = check_episode(scenes * 2, production_spec)
    assert any("상한" in p for p in problems)
