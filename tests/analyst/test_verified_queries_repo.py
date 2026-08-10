from tools.analyst.verified_queries_repo import find_similar


def test_finds_close_match():
    results = find_similar("cual fue el NOI de PT en enero 2024")
    assert results
    assert results[0]["intent"] == "noi_mes"
    assert results[0]["score"] > 0.3


def test_no_match_returns_empty_or_low_score():
    results = find_similar("algo totalmente distinto sobre el clima")
    assert results == [] or results[0]["score"] < 0.2
