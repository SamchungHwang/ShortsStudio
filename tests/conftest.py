from __future__ import annotations

import os

os.environ["ASS_IGNORE_PREFS"] = "1"      # 테스트는 이 PC 의 현재 프로젝트를 보지 않는다. 늘 견본으로 돈다

import pytest

from ass.policy import load_policy
from ass.production.product_bible import load_product_bible
from ass.production.scene_spec import load_scene
from ass.settings import EXAMPLE_DIR


@pytest.fixture(scope="session")
def production_spec() -> dict:
    return load_policy("production_spec").data


@pytest.fixture(scope="session")
def models_config() -> dict:
    return load_policy("models").data


@pytest.fixture(scope="session")
def bible():
    return load_product_bible(EXAMPLE_DIR / "product_bible.yaml")


@pytest.fixture(scope="session")
def scenes():
    folder = EXAMPLE_DIR / "episodes" / "product_intro"
    return [load_scene(p) for p in sorted(folder.glob("scene_*.yaml"))]
