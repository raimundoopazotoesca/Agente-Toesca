from __future__ import annotations

import pytest

from tools.analyst_workspace.percentile import average, nearest_rank_percentile


def test_empty_sample_returns_none_for_percentile_and_average():
    assert nearest_rank_percentile([], 50) is None
    assert nearest_rank_percentile([], 90) is None
    assert average([]) is None


def test_nearest_rank_p50_p90_hand_computed_n4():
    # n=4: p50 -> rank=ceil(0.5*4)=2 -> sorted[1]; p90 -> rank=ceil(0.9*4)=4 -> sorted[3]
    values = [10, 20, 30, 40]
    assert nearest_rank_percentile(values, 50) == 20
    assert nearest_rank_percentile(values, 90) == 40


def test_nearest_rank_p50_p90_hand_computed_n5():
    # n=5: p50 -> rank=ceil(2.5)=3 -> sorted[2]=30; p90 -> rank=ceil(4.5)=5 -> sorted[4]=50
    values = [10, 20, 30, 40, 50]
    assert nearest_rank_percentile(values, 50) == 30
    assert nearest_rank_percentile(values, 90) == 50


def test_nearest_rank_p50_p90_hand_computed_n1():
    values = [42]
    assert nearest_rank_percentile(values, 50) == 42
    assert nearest_rank_percentile(values, 90) == 42


def test_nearest_rank_is_order_independent():
    values = [40, 10, 30, 20]
    assert nearest_rank_percentile(values, 50) == 20
    assert nearest_rank_percentile(values, 90) == 40


def test_nearest_rank_p0_and_p100_are_min_and_max():
    values = [5, 1, 3, 2, 4]
    assert nearest_rank_percentile(values, 0) == 1
    assert nearest_rank_percentile(values, 100) == 5


def test_invalid_percentile_raises():
    with pytest.raises(ValueError):
        nearest_rank_percentile([1, 2, 3], 101)
    with pytest.raises(ValueError):
        nearest_rank_percentile([1, 2, 3], -1)


def test_average_hand_computed():
    assert average([10, 20, 30]) == 20
    assert average([5]) == 5
