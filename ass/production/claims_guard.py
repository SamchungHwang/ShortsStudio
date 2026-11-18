"""제품 표현 가드 (6.5절).

대본 단계(한국어)와 프롬프트 컴파일 단계(영어) 양쪽에서 같은 사전을 적용한다.
사전은 1차 거름망이다. 통과했다고 광고 표현이 적법하다는 뜻이 아니며,
효능·비교 표현은 사람 승인을 거친다(21.1절).
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from ass.production.scene_spec import SceneSpec
from ass.settings import load_config


class Violation(BaseModel):
    term: str
    category: str
    lang: str
    where: str
    excerpt: str


class ClaimsGuard:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or load_config("claims_lexicon")
        self.version: str = str(cfg["version"])
        self.preferred: dict[str, list[str]] = cfg["preferred"]
        self._ko: list[tuple[str, str]] = []
        self._en: list[tuple[str, str, re.Pattern[str]]] = []
        for category, langs in cfg["banned"].items():
            for term in langs.get("ko", []):
                self._ko.append((term, category))
            for term in langs.get("en", []):
                pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
                self._en.append((term, category, pattern))

    def find(self, text: str, where: str = "") -> list[Violation]:
        found: list[Violation] = []
        for term, category in self._ko:
            idx = text.find(term)
            if idx >= 0:
                found.append(Violation(term=term, category=category, lang="ko", where=where,
                                       excerpt=_excerpt(text, idx)))
        for term, category, pattern in self._en:
            m = pattern.search(text)
            if m:
                found.append(Violation(term=term, category=category, lang="en", where=where,
                                       excerpt=_excerpt(text, m.start())))
        return found

    def check_scene(self, scene: SceneSpec) -> list[Violation]:
        """대본 단계 검사: 장면 사양의 모든 서술·내레이션·자막 필드를 본다."""
        found: list[Violation] = []
        found += self.find(scene.setting_en, f"{scene.scene_id}.setting_en")
        if scene.audio_en:
            found += self.find(scene.audio_en, f"{scene.scene_id}.audio_en")
        for i, beat in enumerate(scene.beats):
            base = f"{scene.scene_id}.beats[{i}]"
            for field in ("visual_ko", "visual_en", "camera_en", "narration_ko", "caption_ko"):
                value = getattr(beat, field)
                if value:
                    found += self.find(value, f"{base}.{field}")
        return found


def _excerpt(text: str, idx: int, width: int = 20) -> str:
    return text[max(0, idx - width) : idx + width].strip()
