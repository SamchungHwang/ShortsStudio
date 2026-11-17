"""scene_spec → 영어 영상 프롬프트 컴파일 (6.3절).

- 영상 프롬프트는 영어로 쓴다. 대사는 원문 언어 그대로 따옴표 안에 넣는다.
- negative_prompt 설정값이 없으므로 제외 지시는 프롬프트 본문 끝에 자연어로 쓴다.
- 구간 표기([0-5s])는 쓸 수 있으나 정해진 문법은 아니다. production_spec 에서 끌 수 있다.
- 사전 검사는 두 번 한다: 대본 단계(장면 사양)와 컴파일 단계(완성된 프롬프트).
"""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel

from acs.production.character_bible import CharacterBible
from acs.production.ethics_lexicon import EthicsLexicon, Violation
from acs.production.scene_spec import SceneSpec

COMPILER_VERSION = "0.1.0"

LANG_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese"}


class CompileError(Exception):
    def __init__(self, message: str, violations: list[Violation] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


class CompiledPrompt(BaseModel):
    scene_id: str
    duration_s: int
    aspect_ratio: str
    prompt: str
    prompt_sha256: str
    compiler_version: str = COMPILER_VERSION
    lexicon_version: str
    character_bible_version: str


def compile_scene(
    scene: SceneSpec,
    bible: CharacterBible,
    production_spec: dict[str, Any],
    lexicon: EthicsLexicon | None = None,
) -> CompiledPrompt:
    lexicon = lexicon or EthicsLexicon()

    script_violations = lexicon.check_scene(scene)
    if script_violations:
        raise CompileError(_describe("대본 단계", script_violations), script_violations)

    missing = [i for i, b in enumerate(scene.beats) if not b.action_en]
    if missing:
        raise CompileError(
            f"{scene.scene_id}: action_en 이 비어 있는 구간 {missing}. "
            "한국어 대본을 영어 서술로 옮긴 뒤 컴파일한다."
        )

    shot = production_spec["shot"]
    use_intervals = bool(production_spec.get("prompt", {}).get("interval_notation", True))
    orientation = "Vertical 9:16" if scene.aspect_ratio == "9:16" else "Horizontal 16:9"

    lines: list[str] = [
        f"{orientation} video, {scene.duration_s} seconds, one continuous scene. {shot['style_en']}.",
        f"Setting: {scene.setting_en}",
        "Characters:",
    ]
    for cid in scene.characters:
        c = bible.get(cid)
        lines.append(f"- {c.name_en}: {c.appearance_en}")

    lines.append("Action:")
    for beat in scene.beats:
        parts = [beat.action_en.rstrip(".") + "."]
        if beat.emotion_en:
            parts.append(f"Mood: {beat.emotion_en}.")
        if beat.camera_en:
            parts.append(f"Camera: {beat.camera_en}.")
        if beat.dialogue:
            d = beat.dialogue
            speaker = bible.get(d.speaker).name_en
            lang = LANG_NAMES.get(d.lang, d.lang)
            delivery = f" ({d.delivery_en})" if d.delivery_en else ""
            parts.append(f'{speaker} says in {lang}{delivery}: "{d.text}"')
        prefix = f"[{beat.start_s}-{beat.end_s}s] " if use_intervals else "Then: "
        lines.append(prefix + " ".join(parts))

    if scene.audio_en:
        lines.append(f"Audio: {scene.audio_en}")

    exclusions = list(production_spec.get("exclusions_en", [])) + list(scene.exclusions_en)
    if exclusions:
        lines.append("Constraints: " + ". ".join(e.rstrip(".") for e in exclusions) + ".")

    prompt = "\n".join(lines)

    prompt_violations = lexicon.find(prompt, f"{scene.scene_id}.prompt")
    if prompt_violations:
        raise CompileError(_describe("컴파일 단계", prompt_violations), prompt_violations)

    return CompiledPrompt(
        scene_id=scene.scene_id,
        duration_s=scene.duration_s,
        aspect_ratio=scene.aspect_ratio,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        lexicon_version=lexicon.version,
        character_bible_version=bible.version,
    )


def _describe(stage: str, violations: list[Violation]) -> str:
    items = ", ".join(f"'{v.term}' ({v.where})" for v in violations)
    return f"{stage} 동물 윤리 표현 사전 위반: {items}"
