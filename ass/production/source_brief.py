"""source_brief — 소재 입력의 공통 형식 (6.2절).

아이디어 한 줄, 본인 블로그 글, 본인 영상의 대본을 모두 이 형식으로 모은 뒤 대본으로 바꾼다.
타인의 글·영상은 소재로 받지 않는다. owner_confirmed 가 False 면 다음 단계로 넘기지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ass.settings import load_yaml


class KeyPoint(BaseModel):
    text_ko: str
    evidence: list[str] = []            # product_bible 의 fact id 또는 출처 URL


class SourceBrief(BaseModel):
    brief_id: str
    source_type: Literal["idea", "own_blog", "own_video_script"]
    origin: str | None = None           # 블로그 URL, 영상 URL, 파일 경로
    owner_confirmed: bool               # 본인 소유(또는 사용 권한)를 사람이 확인했는가
    format: Literal["product_intro", "comparison", "info"]
    title_ko: str
    promise_ko: str                     # 시청자에게 하는 약속 하나 (3.1절)
    products: list[str] = []
    key_points: list[KeyPoint] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _checks(self) -> SourceBrief:
        if self.source_type != "idea" and not self.origin:
            raise ValueError("블로그·영상 소재는 origin(출처)을 적어야 한다")
        if not self.owner_confirmed:
            raise ValueError("본인 소유가 확인되지 않은 소재는 쓰지 않는다")
        return self


def load_source_brief(path: str | Path) -> SourceBrief:
    return SourceBrief.model_validate(load_yaml(path))
