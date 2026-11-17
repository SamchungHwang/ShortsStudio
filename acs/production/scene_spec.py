"""scene_spec — 대본에서 15초 장면 사양으로 (6.2절).

컷 단위 프롬프트가 아니라 장면 하나(3~15초)를 구간(beat)으로 나눠 적는다.
한국어 대본(action_ko, 대사)이 원천이고, 영어 필드(*_en)는 프롬프트 컴파일의 입력이다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from acs.settings import load_yaml

MIN_SCENE_S = 3
MAX_SCENE_S = 15


class Dialogue(BaseModel):
    speaker: str                       # 캐릭터 바이블의 id
    text: str                          # 실제로 말할 대사(원문 언어 그대로)
    lang: str = "ko"
    delivery_en: str | None = None     # 말투. 예: "sleepy deadpan"


class Beat(BaseModel):
    start_s: int = Field(ge=0)
    end_s: int = Field(gt=0)
    action_ko: str                     # 대본 원문
    action_en: str | None = None       # 컴파일 입력. 비어 있으면 컴파일하지 않는다
    camera_en: str | None = None
    emotion_en: str | None = None
    dialogue: Dialogue | None = None

    @model_validator(mode="after")
    def _order(self) -> Beat:
        if self.end_s <= self.start_s:
            raise ValueError(f"구간 끝({self.end_s})은 시작({self.start_s})보다 커야 한다")
        return self


class SceneSpec(BaseModel):
    scene_id: str
    episode_id: str
    role: Literal["setup", "escalation", "punchline"]
    duration_s: int = Field(ge=MIN_SCENE_S, le=MAX_SCENE_S)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    characters: list[str] = Field(min_length=1)
    setting_en: str
    beats: list[Beat] = Field(min_length=1)
    audio_en: str | None = None        # 효과음·분위기. BGM은 Lyria로 따로 만든다
    exclusions_en: list[str] = []      # 장면 고유의 제외 지시

    @model_validator(mode="after")
    def _beats_cover_scene(self) -> SceneSpec:
        cursor = 0
        for i, beat in enumerate(self.beats):
            if beat.start_s != cursor:
                raise ValueError(
                    f"{self.scene_id}: {i + 1}번째 구간은 {cursor}초에서 시작해야 한다 "
                    f"(현재 {beat.start_s}초)"
                )
            cursor = beat.end_s
            if beat.dialogue and beat.dialogue.speaker not in self.characters:
                raise ValueError(
                    f"{self.scene_id}: 화자 '{beat.dialogue.speaker}' 가 characters 에 없다"
                )
        if cursor != self.duration_s:
            raise ValueError(
                f"{self.scene_id}: 구간 합({cursor}초)이 duration_s({self.duration_s}초)와 다르다"
            )
        return self


def load_scene(path: str | Path) -> SceneSpec:
    return SceneSpec.model_validate(load_yaml(path))


def check_episode(scenes: list[SceneSpec], production_spec: dict) -> list[str]:
    """한 편의 구성이 production_spec 의 길이 정책에 맞는지 본다. 문제 목록을 돌려준다."""
    ep = production_spec["episode"]
    problems: list[str] = []
    if len(scenes) != ep["scene_count"]:
        problems.append(f"장면 수 {len(scenes)} ≠ {ep['scene_count']}")
    roles = [s.role for s in scenes]
    if roles != ep["scene_roles"]:
        problems.append(f"장면 역할 순서 {roles} ≠ {ep['scene_roles']}")
    total = sum(s.duration_s for s in scenes)
    if total > ep["hard_max_s"]:
        problems.append(f"생성 길이 합 {total}초가 상한 {ep['hard_max_s']}초를 넘는다")
    if total < ep["total_duration_s"]["min"]:
        problems.append(f"생성 길이 합 {total}초가 목표 최소 {ep['total_duration_s']['min']}초보다 짧다")
    return problems
