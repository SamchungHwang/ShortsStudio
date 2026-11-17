"""정책 로더와 policy_hash (14.2~14.3절).

판단 기준은 코드가 아니라 configs/*.yaml 에 있다. 어떤 정책 버전으로 내린 판단인지
추적할 수 있도록, 정책 내용에서 policy_hash 를 계산해 실행 기록과 decision_log 에 남긴다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from acs.settings import CONFIG_DIR, load_yaml


def policy_hash(doc: dict[str, Any]) -> str:
    """정책 내용의 SHA-256 앞 12자리. 키 순서와 YAML 주석·공백에는 영향받지 않는다."""
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


class LoadedPolicy(BaseModel):
    name: str
    path: str
    policy_hash: str
    data: dict[str, Any]


def load_policy(name_or_path: str | Path) -> LoadedPolicy:
    """configs/ 안의 정책 이름(확장자 없이) 또는 파일 경로를 받아 읽는다."""
    path = Path(name_or_path)
    if path.suffix not in {".yaml", ".yml"}:
        path = CONFIG_DIR / f"{name_or_path}.yaml"
    data = load_yaml(path)
    return LoadedPolicy(name=path.stem, path=str(path), policy_hash=policy_hash(data), data=data)
