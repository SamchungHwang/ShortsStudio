import pytest
from pydantic import ValidationError

from ass.production.source_brief import SourceBrief, load_source_brief
from ass.settings import EXAMPLE_DIR


def test_example_brief_points_to_real_facts(bible):
    brief = load_source_brief(EXAMPLE_DIR / "source_briefs" / "aqua_serum_intro.yaml")
    facts = bible.get(brief.products[0]).fact_ids()
    assert all(e in facts for kp in brief.key_points for e in kp.evidence)


def _brief(**overrides) -> dict:
    base = {"brief_id": "b", "source_type": "idea", "owner_confirmed": True, "format": "info",
            "title_ko": "제목", "promise_ko": "약속", "key_points": [{"text_ko": "하나"}]}
    base.update(overrides)
    return base


def test_unconfirmed_ownership_is_rejected():
    with pytest.raises(ValidationError, match="본인 소유"):
        SourceBrief.model_validate(_brief(owner_confirmed=False))


def test_blog_source_needs_origin():
    with pytest.raises(ValidationError, match="origin"):
        SourceBrief.model_validate(_brief(source_type="own_blog"))


def test_more_than_three_key_points_is_rejected():
    with pytest.raises(ValidationError):
        SourceBrief.model_validate(_brief(key_points=[{"text_ko": str(i)} for i in range(4)]))
