from tools.analyst.verified_queries_repo import find_similar


def test_finds_close_match():
    results = find_similar("cual fue el NOI de PT en enero 2024")
    assert results
    assert results[0]["intent"] == "noi_mes"
    assert results[0]["score"] > 0.3


def test_no_match_returns_empty_or_low_score():
    results = find_similar("algo totalmente distinto sobre el clima")
    assert results == [] or results[0]["score"] < 0.2


def test_off_topic_question_returns_empty():
    # No verified-query entry covers LTV or "creditos vigentes"; low lexical
    # overlap with unrelated entries must not surface a misleading hint.
    results = find_similar("cual es el LTV del fondo PT?")
    assert results == []
    results = find_similar("cuantos creditos vigentes tiene el fondo?")
    assert results == []
