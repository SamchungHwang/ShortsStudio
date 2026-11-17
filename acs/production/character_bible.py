"""캐릭터 바이블 (5.1절)."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from acs.settings import load_yaml


class Character(BaseModel):
    id: str
    name_ko: str
    name_en: str
    appearance_en: str          # 모든 장면 프롬프트가 공유하는 외형 서술
    personality_ko: str
    catchphrase_ko: str | None = None
    reference_images: list[str] = []


class CharacterBible(BaseModel):
    version: str
    characters: dict[str, Character]

    def get(self, character_id: str) -> Character:
        try:
            return self.characters[character_id]
        except KeyError:
            raise KeyError(f"캐릭터 바이블에 없는 캐릭터: {character_id}") from None


def load_character_bible(path: str | Path) -> CharacterBible:
    doc = load_yaml(path)
    chars = {cid: Character(id=cid, **body) for cid, body in doc["characters"].items()}
    return CharacterBible(version=str(doc["version"]), characters=chars)
