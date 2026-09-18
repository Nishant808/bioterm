from bioterm.process.sentiment import _compile_phrase, score_text


def test_verb_tense_variant_matches():
    # "misses" is a different tense of "missed" - the literal-phrase matcher
    # this replaces could not see it, so a real trial failure scored as neutral.
    pat = _compile_phrase("missed primary endpoint")
    assert pat.search("the drug misses primary endpoint in its Phase 3 trial")
    assert pat.search("the drug missed its primary endpoint")


def test_plural_noun_variant_matches():
    # "endpoints" (plural) - the old \bphrase\b match failed on the trailing "s".
    pat = _compile_phrase("meets primary endpoint")
    assert pat.search("the company meets primary endpoints in the pivotal study")


def test_optional_filler_word_between_phrase_words():
    pat = _compile_phrase("meets primary endpoint")
    assert pat.search("the drug met the primary endpoint")
    assert pat.search("the drug met its primary endpoint")


def test_auxiliary_verb_variant_matches():
    pat = _compile_phrase("did not meet")
    assert pat.search("the study does not meet the bar")
    assert pat.search("the study did not meet its goal")


def test_no_false_positive_from_shared_prefix_words():
    # "complete response letter" must not fire on unrelated uses of "complete"
    # and "response" that never mention a letter.
    pat = _compile_phrase("complete response letter")
    assert not pat.search("the company completes its response to the FDA's request")


def test_score_text_catches_previously_missed_failure_language():
    v, tags, es = score_text("Drug misses primary endpoint in Phase 3 trial")
    assert es < 0
    assert "missed primary endpoint" in tags


def test_score_text_catches_previously_missed_plural_success_language():
    v, tags, es = score_text("Company meets primary endpoints in pivotal study")
    assert es > 0
    assert "meets primary endpoint" in tags


def test_score_text_no_signal_on_unrelated_completion_language():
    v, tags, es = score_text("Company completes response to FDA information request")
    assert es == 0.0
    assert tags == ""


def test_score_text_drops_positive_echo_inside_longer_negative_phrase():
    # "approval" (positive) is a literal substring of "voted against approval"
    # (negative) - it must not also count as an independent positive signal.
    v, tags, es = score_text("Panel voted against approval of the drug")
    assert es < 0
    assert tags == "voted against approval"


def test_score_text_empty_input():
    v, tags, es = score_text("", "")
    assert v == 0.0
    assert tags == ""
    assert es == 0.0
