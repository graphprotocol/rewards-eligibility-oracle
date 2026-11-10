"""
The stake-scaled subgraph minimum: how many subgraphs an indexer must serve each day for that day to
count as online, given its total stake.
"""

from decimal import Decimal
from typing import Optional

# GRT has 18 decimals, so stake read from the chain is in units of 10^-18 GRT
WEI_PER_GRT = 10**18


def required_subgraphs(stake_wei: int, min_subgraphs: int, grt_per_subgraph: Optional[int]) -> int:
    """
    Return how many subgraphs an indexer with stake_wei of total stake must serve each day.

    That is 1 subgraph per grt_per_subgraph GRT, rounded up, and never fewer than min_subgraphs. With
    no grt_per_subgraph every indexer needs min_subgraphs. Worked in wei so the rounding is exact: at
    1 per 4M GRT, 40M GRT needs 10 subgraphs and 1 wei more needs 11.
    """
    if grt_per_subgraph is None:
        return min_subgraphs

    # Ceiling division, which stays exact for amounts far beyond a float's precision
    steps = -(-stake_wei // (grt_per_subgraph * WEI_PER_GRT))

    return max(min_subgraphs, steps)


def format_grt(stake_wei: int) -> str:
    """Write a wei amount as exact GRT with no trailing zeros, so a required count can be checked by hand."""
    grt = Decimal(stake_wei).scaleb(-18).normalize()

    return format(grt, "f")
