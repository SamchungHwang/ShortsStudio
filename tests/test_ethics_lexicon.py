from acs.production.ethics_lexicon import EthicsLexicon


def test_banned_terms_found_in_both_languages():
    lex = EthicsLexicon()
    assert [v.term for v in lex.find("모모가 무서워서 떠는 장면")] == ["무서워서 떠는"]
    assert [v.term for v in lex.find("A Scared cat, TREMBLING.")] == ["scared", "trembling"]


def test_preferred_terms_pass():
    lex = EthicsLexicon()
    for text in lex.preferred["ko"] + lex.preferred["en"]:
        assert lex.find(text) == []


def test_english_match_is_whole_word():
    assert EthicsLexicon().find("an untrappedness test, scaredy") == []


def test_running_example_is_clean(scenes):
    lex = EthicsLexicon()
    for scene in scenes:
        assert lex.check_scene(scene) == []
