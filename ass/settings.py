"""저장소 경로와 공통 설정 로더.

작업하는 곳은 둘 가운데 하나다.
  견본      examples/moalab_skincare      책의 예제. 산출물은 outputs/ 에 쌓인다
  프로젝트   projects/<이름>/              독자의 작업. 산출물은 projects/<이름>/outputs/ 에 쌓인다

어느 쪽인지는 이 모듈을 읽을 때 한 번 정한다. 환경 변수 ASS_PROJECT 가 먼저고, 없으면
`ass init` 이나 콘솔이 .ass_console.json 에 적어 둔 현재 프로젝트를 쓴다. 둘 다 없으면 견본이다.
EXAMPLE_DIR 라는 이름은 처음부터 쓰던 것이라 남겨 두었다. 지금 작업하는 폴더를 가리킨다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
SAMPLE_DIR = ROOT / "examples" / "moalab_skincare"
SAMPLE_NAME = "sample"                       # 견본을 가리키는 이름. 프로젝트 이름으로 쓸 수 없다
# 아래 둘은 환경 변수로 다른 곳을 가리킬 수 있다. 테스트가 실제 폴더를 건드리지 않게 하는 데 쓴다
PROJECTS_DIR = Path(os.environ.get("ASS_PROJECTS_DIR") or ROOT / "projects")
PREFS_PATH = Path(os.environ.get("ASS_PREFS_PATH") or ROOT / ".ass_console.json")   # 현재 프로젝트, 콘솔 글자 크기


def read_prefs(path: Path = PREFS_PATH) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def write_prefs(changes: dict[str, Any], path: Path = PREFS_PATH) -> None:
    doc = read_prefs(path)
    doc.update(changes)
    try:
        path.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass                                  # 저장하지 못해도 그대로 쓴다


def valid_project_name(name: str) -> bool:
    """폴더 이름과 명령 인자로 쓰이므로 영문 소문자, 숫자, 밑줄만 받는다."""
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{1,39}", name)) and name != SAMPLE_NAME


def list_projects(projects_dir: Path = PROJECTS_DIR) -> list[str]:
    if not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir() if p.is_dir() and (p / "product_bible.yaml").is_file())


def resolve_project(env: dict[str, str] | None = None, prefs: dict[str, Any] | None = None,
                    projects_dir: Path = PROJECTS_DIR) -> str:
    """지금 작업할 곳의 이름. 견본이면 SAMPLE_NAME."""
    env = os.environ if env is None else env
    if env.get("ASS_IGNORE_PREFS"):            # 테스트는 PC 의 설정을 보지 않는다
        return SAMPLE_NAME
    name = env.get("ASS_PROJECT") or (read_prefs() if prefs is None else prefs).get("project") or SAMPLE_NAME
    if name != SAMPLE_NAME and not (projects_dir / name / "product_bible.yaml").is_file():
        return SAMPLE_NAME                     # 지워진 프로젝트를 가리키고 있으면 견본으로 돌아간다
    return str(name)


def project_paths(name: str, projects_dir: Path = PROJECTS_DIR) -> tuple[Path, Path]:
    """(작업 폴더, 산출물 폴더)."""
    if name == SAMPLE_NAME:
        return SAMPLE_DIR, ROOT / "outputs"
    return projects_dir / name, projects_dir / name / "outputs"


PROJECT = resolve_project()
EXAMPLE_DIR, OUTPUT_DIR = project_paths(PROJECT)
PROJECT_DIR = EXAMPLE_DIR


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: 최상위가 매핑이 아니다")
    return doc


def load_config(name: str) -> dict[str, Any]:
    """configs/<name>.yaml 을 읽는다."""
    return load_yaml(CONFIG_DIR / f"{name}.yaml")
