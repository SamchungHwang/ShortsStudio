"""저장소 경로와 공통 설정 로더."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
OUTPUT_DIR = ROOT / "outputs"
EXAMPLE_DIR = ROOT / "examples" / "momo_monday_meeting"


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: 최상위가 매핑이 아니다")
    return doc


def load_config(name: str) -> dict[str, Any]:
    """configs/<name>.yaml 을 읽는다."""
    return load_yaml(CONFIG_DIR / f"{name}.yaml")
