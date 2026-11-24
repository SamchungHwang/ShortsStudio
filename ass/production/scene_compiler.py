"""scene_spec → 영어 영상 프롬프트 + 내레이션 대본 컴파일 (6.4절).

- 영상 프롬프트는 영어로 쓴다. negative_prompt 설정값이 없으므로 제외 지시는 본문 끝에 자연어로 쓴다.
- 구간 표기([0-5s])는 쓸 수 있으나 정해진 문법은 아니다. production_spec 에서 끌 수 있다.
- 내레이션은 production_spec.narration.mode 를 따른다.
    tts      : 영상에는 음성을 넣지 않는다. 내레이션은 구간별 대본으로 따로 내보내 TTS로 만든다(11장).
    in_video : 내레이션을 프롬프트에 넣어 영상과 함께 생성한다.
- 가드는 두 번 건다: 대본 단계(장면 사양)와 컴파일 단계(완성된 프롬프트).
- 내레이션·자막이 드는 근거(evidence)는 그 장면 제품의 product_bible 사실이어야 한다.
"""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel

from ass.production.claims_guard import ClaimsGuard, Violation
from ass.production.product_bible import ProductBible, find_dont_say
from ass.production.scene_spec import SceneSpec

COMPILER_VERSION = "0.2.0"

LANG_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese"}


class CompileError(Exception):
    def __init__(self, message: str, violations: list[Violation] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []


class NarrationLine(BaseModel):
    start_s: int
    end_s: int
    text: str
    caption: str | None = None
    evidence: list[str] = []


class CompiledScene(BaseModel):
    scene_id: str
    duration_s: int
    aspect_ratio: str
    prompt: str
    prompt_sha256: str
    narration_mode: str
    narration: list[NarrationLine]
    needs_human_approval: bool         # 타사 제품이 나오면 True
    compiler_version: str = COMPILER_VERSION
    lexicon_version: str
    product_bible_version: str


def compile_scene(
    scene: SceneSpec,
    bible: ProductBible,
    production_spec: dict[str, Any],
    guard: ClaimsGuard | None = None,
) -> CompiledScene:
    guard = guard or ClaimsGuard()

    script_violations = guard.check_scene(scene)
    if script_violations:
        raise CompileError(_describe("대본 단계", script_violations), script_violations)

    missing = [i for i, b in enumerate(scene.beats) if not b.visual_en]
    if missing:
        raise CompileError(
            f"{scene.scene_id}: visual_en 이 비어 있는 구간 {missing}. "
            "한국어 대본을 영어 서술로 옮긴 뒤 컴파일한다."
        )

    products = [bible.get(pid) for pid in scene.products]
    known_facts = set().union(*(p.fact_ids() for p in products)) if products else set()
    for i, beat in enumerate(scene.beats):
        unknown = [e for e in beat.evidence if e not in known_facts]
        if unknown:
            raise CompileError(
                f"{scene.scene_id}.beats[{i}]: product_bible 에 없는 근거 {unknown}. "
                "사실은 제품 바이블에 먼저 적고 출처를 남긴다."
            )

    for i, beat in enumerate(scene.beats):          # 제품마다 정해 둔 '쓰지 않는 표현' (5.1절)
        spoken = " ".join(t for t in (beat.narration_ko, beat.caption_ko) if t)
        for product in products:
            for dont in find_dont_say(product, spoken):
                raise CompileError(
                    f"{scene.scene_id}.beats[{i}]: '{dont.text_ko}' 는 {product.name_ko} 에 쓰지 않기로 한 표현이다. "
                    f"이유: {dont.reason}")

    shot = production_spec["shot"]
    fmt = production_spec.get("formats", {}).get(scene.format, {})      # 형식이 분위기와 제외 지시를 따로 정할 수 있다
    style_en = fmt.get("style_en", shot["style_en"])
    narration_cfg = production_spec.get("narration", {})
    mode = narration_cfg.get("mode", "tts")
    lang = LANG_NAMES.get(narration_cfg.get("language", "ko"), "Korean")
    use_intervals = bool(production_spec.get("prompt", {}).get("interval_notation", True))
    orientation = "Vertical 9:16" if scene.aspect_ratio == "9:16" else "Horizontal 16:9"

    lines: list[str] = [
        f"{orientation} video, {scene.duration_s} seconds, one continuous scene. {style_en}.",
        f"Setting: {scene.setting_en}",
    ]
    if products:
        lines.append("Products (keep shape, color and label exactly as described):")
        lines += [f"- {p.name_en}: {p.appearance_en}" for p in products]

    lines.append("Action:")
    narration: list[NarrationLine] = []
    for beat in scene.beats:
        parts = [beat.visual_en.rstrip(".") + "."]
        if beat.camera_en:
            parts.append(f"Camera: {beat.camera_en}.")
        if beat.narration_ko:
            narration.append(NarrationLine(start_s=beat.start_s, end_s=beat.end_s,
                                           text=beat.narration_ko, caption=beat.caption_ko,
                                           evidence=beat.evidence))
            if mode == "in_video":
                parts.append(f'An off-screen narrator says in {lang}, calm and clear: "{beat.narration_ko}"')
        prefix = f"[{beat.start_s}-{beat.end_s}s] " if use_intervals else "Then: "
        lines.append(prefix + " ".join(parts))

    if scene.audio_en:
        lines.append(f"Audio: {scene.audio_en}")

    exclusions = list(fmt.get("exclusions_en", production_spec.get("exclusions_en", []))) + list(scene.exclusions_en)
    if mode == "tts":
        exclusions.append("No speech, narration or voice-over")
    if exclusions:
        lines.append("Constraints: " + ". ".join(e.rstrip(".") for e in exclusions) + ".")

    prompt = "\n".join(lines)

    prompt_violations = guard.find(prompt, f"{scene.scene_id}.prompt")
    if prompt_violations:
        raise CompileError(_describe("컴파일 단계", prompt_violations), prompt_violations)

    return CompiledScene(
        scene_id=scene.scene_id,
        duration_s=scene.duration_s,
        aspect_ratio=scene.aspect_ratio,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        narration_mode=mode,
        narration=narration,
        needs_human_approval=any(not p.is_own for p in products),
        lexicon_version=guard.version,
        product_bible_version=bible.version,
    )


def _describe(stage: str, violations: list[Violation]) -> str:
    items = ", ".join(f"'{v.term}' [{v.category}] ({v.where})" for v in violations)
    return f"{stage} 제품 표현 가드 위반: {items}"
