from __future__ import annotations

import pytest

from acs.policy import load_policy
from acs.production.character_bible import load_character_bible
from acs.production.scene_spec import load_scene
from acs.settings import EXAMPLE_DIR


@pytest.fixture(scope="session")
def production_spec() -> dict:
    return load_policy("production_spec").data


@pytest.fixture(scope="session")
def models_config() -> dict:
    return load_policy("models").data


@pytest.fixture(scope="session")
def bible():
    return load_character_bible(EXAMPLE_DIR / "character_bible.yaml")


@pytest.fixture(scope="session")
def scenes():
    return [load_scene(p) for p in sorted((EXAMPLE_DIR / "scenes").glob("scene_*.yaml"))]
