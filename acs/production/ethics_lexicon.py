"""동물 윤리 표현 사전 검사 (6.4절).

대본 단계(한국어)와 프롬프트 컴파일 단계(영어) 양쪽에서 같은 사전을 적용한다.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from acs.production.scene_spec import SceneSpec
from acs.settings import load_config


class Violation(BaseModel):
    term: str
    lang: str
    where: str
    excerpt: str


class EthicsLexicon:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or load_config("ethics_lexicon")
        self.version: str = str(cfg["version"])
        self.banned_ko: list[str] = list(cfg["banned"]["ko"])
        self.banned_en: list[str] = list(cfg["banned"]["en"])
        self.preferred: dict[str, list[str]] = cfg["preferred"]
        self._en_patterns = [
            (t, re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)) for t in self.banned_en
        ]

    def find(self, text: str, where: str = "") -> list[Violation]:
        found: list[Violation] = []
        for term in self.banned_ko:
            idx = text.find(term)
            if idx >= 0:
                found.append(Violation(term=term, lang="ko", where=where, excerpt=_excerpt(text, idx)))
        for term, pattern in self._en_patterns:
            m = pattern.search(text)
            if m:
                found.append(
                    Violation(term=term, lang="en", where=where, excerpt=_excerpt(text, m.start()))
                )
        return found

    def check_scene(self, scene: SceneSpec) -> list[Violation]:
        """대본 단계 검사: 장면 사양의 모든 서술·대사 필드를 본다."""
        found: list[Violation] = []
        found += self.find(scene.setting_en, f"{scene.scene_id}.setting_en")
        if scene.audio_en:
            found += self.find(scene.audio_en, f"{scene.scene_id}.audio_en")
        for i, beat in enumerate(scene.beats):
            base = f"{scene.scene_id}.beats[{i}]"
            for field in ("action_ko", "action_en", "camera_en", "emotion_en"):
                value = getattr(beat, field)
                if value:
                    found += self.find(value, f"{base}.{field}")
            if beat.dialogue:
                found += self.find(beat.dialogue.text, f"{base}.dialogue.text")
                if beat.dialogue.delivery_en:
                    found += self.find(beat.dialogue.delivery_en, f"{base}.dialogue.delivery_en")
        return found


def _excerpt(text: str, idx: int, width: int = 20) -> str:
    return text[max(0, idx - width) : idx + width].strip()
