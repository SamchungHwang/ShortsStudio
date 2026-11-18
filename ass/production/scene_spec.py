"""scene_spec — 소재에서 15초 장면 사양으로 (6.3절).

컷 단위 프롬프트가 아니라 장면 하나(3~15초)를 구간(beat)으로 나눠 적는다.
한국어 대본(visual_ko, 내레이션, 자막)이 원천이고, 영어 필드(*_en)는 프롬프트 컴파일의 입력이다.
내레이션이 제품 사실을 말하면 그 근거(product_bible 의 fact id)를 evidence 에 적는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ass.settings import load_yaml

MIN_SCENE_S = 3
MAX_SCENE_S = 15

Format = Literal["product_intro", "comparison", "info"]


class Beat(BaseModel):
    start_s: int = Field(ge=0)
    end_s: int = Field(gt=0)
    visual_ko: str                     # 화면에 보이는 것 (대본 원문)
    visual_en: str | None = None       # 컴파일 입력. 비어 있으면 컴파일하지 않는다
    camera_en: str | None = None
    narration_ko: str | None = None    # 이 구간에 읽을 내레이션
    caption_ko: str | None = None      # 화면 자막. 조립 단계(12장)에서 얹는다
    evidence: list[str] = []           # 내레이션·자막의 근거가 되는 fact id

    @model_validator(mode="after")
    def _order(self) -> Beat:
        if self.end_s <= self.start_s:
            raise ValueError(f"구간 끝({self.end_s})은 시작({self.start_s})보다 커야 한다")
        return self


class SceneSpec(BaseModel):
    scene_id: str
    episode_id: str
    format: Format
    role: str                          # 형식별 장면 역할. production_spec.formats 와 대조한다
    duration_s: int = Field(ge=MIN_SCENE_S, le=MAX_SCENE_S)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    products: list[str] = []           # product_bible 의 id. 정보 전달 형식은 비울 수 있다
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
        if cursor != self.duration_s:
            raise ValueError(
                f"{self.scene_id}: 구간 합({cursor}초)이 duration_s({self.duration_s}초)와 다르다"
            )
        return self


def load_scene(path: str | Path) -> SceneSpec:
    return SceneSpec.model_validate(load_yaml(path))


def check_episode(scenes: list[SceneSpec], production_spec: dict[str, Any]) -> list[str]:
    """한 편의 구성이 production_spec 의 형식·길이 정책에 맞는지 본다. 문제 목록을 돌려준다."""
    ep = production_spec["episode"]
    problems: list[str] = []
    formats = {s.format for s in scenes}
    if len(formats) != 1:
        return [f"한 편 안에 형식이 섞여 있다: {sorted(formats)}"]
    fmt = production_spec["formats"][scenes[0].format]

    if len(scenes) != ep["scene_count"]:
        problems.append(f"장면 수 {len(scenes)} ≠ {ep['scene_count']}")
    roles = [s.role for s in scenes]
    if roles != fmt["scene_roles"]:
        problems.append(f"장면 역할 순서 {roles} ≠ {fmt['scene_roles']} ({fmt['name_ko']})")
    products = {p for s in scenes for p in s.products}
    if len(products) < fmt["min_products"]:
        problems.append(f"{fmt['name_ko']} 형식은 제품이 {fmt['min_products']}개 이상 필요하다 (현재 {len(products)})")
    total = sum(s.duration_s for s in scenes)
    if total > ep["hard_max_s"]:
        problems.append(f"생성 길이 합 {total}초가 상한 {ep['hard_max_s']}초를 넘는다")
    if total < ep["total_duration_s"]["min"]:
        problems.append(f"생성 길이 합 {total}초가 목표 최소 {ep['total_duration_s']['min']}초보다 짧다")

    max_chars = production_spec["caption"]["max_chars"]
    for s in scenes:
        for i, b in enumerate(s.beats):
            if b.caption_ko and len(b.caption_ko.replace(" ", "")) > max_chars:
                problems.append(f"{s.scene_id}.beats[{i}] 자막이 {max_chars}자를 넘는다: {b.caption_ko}")
    return problems
