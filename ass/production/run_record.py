"""실행 기록 (2.5절, 4.3절). 호출마다 api_run.json 을 남긴다.

모델 ID, SDK 버전, 일시, 요청, 추정 비용, 처리 시간을 함께 적어 두면
'검증 일자' 상자와 부록 A의 실험 기록을 이 파일에서 그대로 옮길 수 있다.
"""
from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _sdk_version() -> str | None:
    try:
        return metadata.version("google-genai")
    except metadata.PackageNotFoundError:
        return None


class RunRecord(BaseModel):
    run_id: str
    purpose: str                               # 예: "ch02 first render", "E01 reference limit"
    episode: str | None = None                 # 편 이름. 비용 장부(ass cost)가 편별로 묶는 데 쓴다
    scene_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model: str
    sdk: str = "google-genai"
    sdk_version: str | None = Field(default_factory=_sdk_version)
    python_version: str = Field(default_factory=platform.python_version)
    request: dict[str, Any]
    mode: str = "text"                         # 생성 모드 (7장): text | reference | image | frames
    inputs: list[dict[str, Any]] = []          # 함께 보낸 이미지 (태그, 제품, 방향, sha256 앞 12자)
    approved_by: str | None = None             # 타사 제품이 나오는 장면을 승인한 사람
    prompt_sha256: str | None = None
    policy_hashes: dict[str, str] = {}
    interaction_id: str | None = None
    output_path: str | None = None
    elapsed_s: float | None = None
    estimated_cost_usd: float | None = None    # 추정값. 실제 청구액은 결제 화면에서 확인해 billed_cost_usd 에 적는다
    billed_cost_usd: float | None = None
    status: str = "ok"                         # ok | error | dry_run
    attempts: int = 0                          # 실제로 호출한 횟수. dry_run 은 0
    attempt_errors: list[str] = []             # 다시 시도하기 전에 났던 오류 (4.4절)
    error: str | None = None
    notes: str | None = None

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return out
