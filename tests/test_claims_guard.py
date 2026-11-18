from ass.production.claims_guard import ClaimsGuard


def test_banned_terms_found_with_category():
    guard = ClaimsGuard()
    found = guard.find("여드름 개선에 최고인 세럼")
    assert {(v.term, v.category) for v in found} == {
        ("여드름 개선", "medical_claim"), ("최고", "absolute_claim")}
    found = guard.find("It CURES dryness, guaranteed.")
    assert [v.term for v in found] == ["cures", "guaranteed"]


def test_disparagement_is_caught():
    assert ClaimsGuard().find("하루온 선크림은 쓰면 안 되는 제품")[0].category == "disparagement"


def test_english_match_is_whole_word():
    assert ClaimsGuard().find("the bestseller shelf, a healthy glow") == []


def test_running_example_is_clean(scenes):
    guard = ClaimsGuard()
    for scene in scenes:
        assert guard.check_scene(scene) == []
