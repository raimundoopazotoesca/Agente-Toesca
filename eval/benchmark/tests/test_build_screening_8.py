from eval.round_b.build_screening_8 import scrub


def test_scrub_removes_hidden_reasoning_recursively():
    assert scrub({"final_answer": "ok", "thinking": "secret", "nested": [{"type": "reasoning", "text": "secret"}]}) == {"final_answer": "ok", "nested": []}
