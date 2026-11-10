"""
Unit tests for the stake-scaled subgraph minimum.
"""

import pytest

from src.utils.subgraph_minimum import WEI_PER_GRT, format_grt, required_subgraphs

# 1 subgraph per 4M GRT, the first stage of the stake-scaled minimum
GRT_PER_SUBGRAPH = 4_000_000
MIN_SUBGRAPHS = 10


@pytest.mark.parametrize(
    "stake_grt, expected",
    [
        (0, 10),
        (10_000_000, 10),
        (30_000_000, 10),
        (40_000_000, 10),
        (41_000_000, 11),
        (50_000_000, 13),
        (100_000_000, 25),
        (200_000_000, 50),
    ],
)
def test_required_subgraphs_matches_the_published_examples(stake_grt: int, expected: int):
    """
    Tests the required count against every example in the published eligibility criteria.
    """
    assert required_subgraphs(stake_grt * WEI_PER_GRT, MIN_SUBGRAPHS, GRT_PER_SUBGRAPH) == expected


def test_required_subgraphs_rounds_up_from_the_smallest_amount_over_a_step():
    """
    Tests that the rounding is exact, so 1 wei over a whole number of steps needs 1 more subgraph.
    """
    exactly_40m = 40_000_000 * WEI_PER_GRT

    assert required_subgraphs(exactly_40m, MIN_SUBGRAPHS, GRT_PER_SUBGRAPH) == 10
    assert required_subgraphs(exactly_40m + 1, MIN_SUBGRAPHS, GRT_PER_SUBGRAPH) == 11


def test_required_subgraphs_is_min_subgraphs_when_the_minimum_does_not_scale():
    """
    Tests that without a GRT_PER_SUBGRAPH every indexer needs MIN_SUBGRAPHS, whatever its stake.
    """
    assert required_subgraphs(500_000_000 * WEI_PER_GRT, MIN_SUBGRAPHS, None) == MIN_SUBGRAPHS


@pytest.mark.parametrize(
    "stake_wei, expected",
    [
        (0, "0"),
        (145_300_000 * WEI_PER_GRT, "145300000"),
        (145_300_000 * WEI_PER_GRT + WEI_PER_GRT // 2, "145300000.5"),
        (1, "0.000000000000000001"),
    ],
)
def test_format_grt_writes_exact_grt(stake_wei: int, expected: str):
    """
    Tests that stake is written as exact GRT, never rounded, so a required count can be checked by hand.
    """
    assert format_grt(stake_wei) == expected
