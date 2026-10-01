"""
Unit tests for the DataEdge payload codec.
"""

from datetime import date

import pytest

from src.utils.data_edge_codec import (
    ENCODING_VERSION,
    PAYLOAD_MAGIC,
    PayloadError,
    _decode_varint,
    _encode_varint,
    decode_payload,
    encode_payload,
    select_days_to_publish,
)

# --- Test Constants ---
RUN_DATE = date(2026, 9, 25)
WINDOW_START = date(2026, 8, 28)
WINDOW_END = date(2026, 9, 25)
CRITERIA = {"MIN_ONLINE_DAYS": 5, "MIN_SUBGRAPHS": 1, "MAX_LATENCY_MS": 5000, "MAX_BLOCKS_BEHIND": 50000}
INDEXER_A = "0x32bbd16a94ebb289edceebe77f35acc82664157b"
INDEXER_B = "0x474e571ab6dd77489ec3c7ddf9cbc893fcba684c"


def _row(day: str, indexer: str, **overrides) -> dict:
    """Build a per-day metrics row with all counters defaulted to zero."""
    row = {
        "day": day,
        "indexer": indexer,
        "query_attempts": 0,
        "qualifying_queries": 0,
        "qualifying_subgraphs": 0,
        "failed_status": 0,
        "failed_latency": 0,
        "failed_blocks_behind": 0,
        "is_online_day": 0,
    }
    row.update(overrides)

    return row


@pytest.fixture
def daily_rows() -> list:
    """Provides rows spanning the whole window, including days outside the published range."""
    return [
        _row("2026-09-01", INDEXER_A, query_attempts=99, qualifying_queries=99, is_online_day=1),
        _row("2026-09-24", INDEXER_A, query_attempts=3184, qualifying_queries=2761, is_online_day=1),
        _row("2026-09-24", INDEXER_B, query_attempts=29, failed_blocks_behind=29),
        _row("2026-09-25", INDEXER_A, query_attempts=2905, qualifying_queries=2488, is_online_day=1),
        _row("2026-09-25", INDEXER_B),
    ]


# --- Tests for varint encoding ---


@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 300, 16383, 16384, 2**32, 2**64 - 1])
def test_varint_round_trips(value: int):
    """
    Tests that varints survive a round trip across the byte-boundary values where the encoding changes
    length.
    """
    encoded = _encode_varint(value)
    decoded, offset = _decode_varint(encoded, 0)

    assert decoded == value
    assert offset == len(encoded)


def test_encode_varint_rejects_negative_values():
    """
    Tests that a negative counter is rejected rather than silently encoded as something enormous.
    """
    with pytest.raises(PayloadError, match="negative"):
        _encode_varint(-1)


def test_decode_varint_rejects_a_truncated_payload():
    """
    Tests that a payload ending mid-varint is reported rather than decoded as a partial value.
    """
    with pytest.raises(PayloadError, match="ended in the middle"):
        _decode_varint(b"\x80", 0)


# --- Tests for select_days_to_publish() ---


def test_select_days_to_publish_returns_trailing_days_oldest_first():
    """
    Tests that the published range ends on the window's last day and runs backwards from it.
    """
    assert select_days_to_publish(WINDOW_START, WINDOW_END, 3) == [
        date(2026, 9, 23),
        date(2026, 9, 24),
        WINDOW_END,
    ]


def test_select_days_to_publish_never_reaches_past_the_window_start():
    """
    Tests that asking for more days than the window holds publishes the window instead of days that
    were never analysed. The clamp lives here so every caller agrees on which days a run publishes.
    """
    short_window_start = date(2026, 9, 24)

    assert select_days_to_publish(short_window_start, WINDOW_END, 7) == [short_window_start, WINDOW_END]


def test_select_days_to_publish_rejects_an_inverted_window():
    """
    Tests that a window whose end precedes its start is rejected rather than publishing nothing.
    """
    with pytest.raises(PayloadError, match="is before window_start"):
        select_days_to_publish(WINDOW_END, WINDOW_START, 2)


def test_select_days_to_publish_rejects_an_empty_range():
    """
    Tests that a misconfigured publish window is rejected rather than publishing nothing silently.
    """
    with pytest.raises(PayloadError, match="at least 1"):
        select_days_to_publish(WINDOW_START, WINDOW_END, 0)


# --- Tests for encode_payload() / decode_payload() ---


def test_payload_round_trips(daily_rows: list):
    """
    Tests that a payload decodes back to the run info, criteria and per-day rows it was built from,
    which is what a subgraph mapping has to be able to do.
    """
    # Act
    payload = encode_payload(
        run_date=RUN_DATE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        criteria=CRITERIA,
        daily_rows=daily_rows,
        indexers_evaluated=189,
        indexers_eligible=142,
        days=select_days_to_publish(WINDOW_START, WINDOW_END, 2),
    )
    decoded = decode_payload(payload)

    # Assert: provenance and criteria survive
    assert decoded["version"] == ENCODING_VERSION
    assert decoded["run_info"] == {
        "run_date": RUN_DATE,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "indexers_evaluated": 189,
        "indexers_eligible": 142,
    }
    assert decoded["criteria"] == CRITERIA

    # Assert: only the trailing days are published, oldest first
    assert [day["day"] for day in decoded["daily_metrics"]] == [date(2026, 9, 24), RUN_DATE]

    # Assert: counters survive for a day with more than one indexer
    first_day = decoded["daily_metrics"][0]["rows"]
    assert len(first_day) == 2
    by_indexer = {row["indexer"]: row for row in first_day}
    assert by_indexer[INDEXER_A]["query_attempts"] == 3184
    assert by_indexer[INDEXER_A]["qualifying_queries"] == 2761
    assert by_indexer[INDEXER_A]["is_online_day"] == 1
    assert by_indexer[INDEXER_B]["failed_blocks_behind"] == 29
    assert by_indexer[INDEXER_B]["is_online_day"] == 0


def test_encode_payload_omits_indexers_routed_nothing(daily_rows: list):
    """
    Tests that a day on which an indexer received no attempts contributes no row, since absence is
    what encodes the zero row for the subgraph.
    """
    # Act
    payload = encode_payload(
        run_date=RUN_DATE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        criteria=CRITERIA,
        daily_rows=daily_rows,
        indexers_evaluated=2,
        indexers_eligible=1,
        days=select_days_to_publish(WINDOW_START, WINDOW_END, 2),
    )
    decoded = decode_payload(payload)

    # Assert: 0x474e was routed nothing on the final day, so only 0x32bb appears
    final_day = decoded["daily_metrics"][1]
    assert [row["indexer"] for row in final_day["rows"]] == [INDEXER_A]


def test_encode_payload_omits_a_day_nobody_served():
    """
    Tests that a day on which no indexer was routed anything is omitted rather than published as every
    indexer having served nothing. That means its source data has not arrived, and publishing zeros
    would record it as a network-wide idle day that only the overlap could restate.
    """
    # Act: the published day has a row, but with no attempts on it
    payload = encode_payload(
        run_date=RUN_DATE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        criteria=CRITERIA,
        daily_rows=[_row("2026-09-25", INDEXER_A)],
        indexers_evaluated=1,
        indexers_eligible=0,
        days=select_days_to_publish(WINDOW_START, WINDOW_END, 1),
    )

    # Assert
    assert decode_payload(payload)["daily_metrics"] == []


def test_encode_payload_publishes_only_the_days_that_have_data():
    """
    Tests that a day with data is still published when the day beside it has none, so one day's
    missing source data does not hold back the day that is ready.
    """
    # Act: 2026-09-24 was routed nothing, 2026-09-25 was served
    payload = encode_payload(
        run_date=RUN_DATE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        criteria=CRITERIA,
        daily_rows=[
            _row("2026-09-24", INDEXER_A),
            _row("2026-09-25", INDEXER_A, query_attempts=12, qualifying_queries=12, is_online_day=1),
        ],
        indexers_evaluated=1,
        indexers_eligible=1,
        days=select_days_to_publish(WINDOW_START, WINDOW_END, 2),
    )
    decoded = decode_payload(payload)

    # Assert: only the day with data is on the wire
    assert [day["day"] for day in decoded["daily_metrics"]] == [RUN_DATE]
    assert decoded["daily_metrics"][0]["rows"][0]["query_attempts"] == 12


def test_encode_payload_stays_compact(daily_rows: list):
    """
    Tests that the encoding stays small enough to publish daily, since the whole design depends on a
    payload costing less than the renewal transactions it accompanies.
    """
    # Arrange: a realistic run, 200 indexers active across both published days
    rows = []
    for day in ("2026-09-24", "2026-09-25"):
        for i in range(200):
            indexer = "0x" + f"{i:040x}"
            rows.append(
                _row(
                    day,
                    indexer,
                    query_attempts=12345,
                    qualifying_queries=12000,
                    qualifying_subgraphs=8,
                    failed_status=200,
                    failed_latency=100,
                    failed_blocks_behind=45,
                    is_online_day=1,
                )
            )

    # Act
    payload = encode_payload(
        run_date=RUN_DATE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        criteria=CRITERIA,
        daily_rows=rows,
        indexers_evaluated=200,
        indexers_eligible=180,
        days=select_days_to_publish(WINDOW_START, WINDOW_END, 2),
    )

    # Assert: comfortably under 16 KB for 400 published rows
    assert len(payload) < 16_000
    assert len(decode_payload(payload)["daily_metrics"][0]["rows"]) == 200


def test_encode_payload_fails_on_missing_criteria(daily_rows: list):
    """
    Tests that a payload cannot be published without the thresholds needed to interpret it.
    """
    with pytest.raises(PayloadError, match="missing MAX_LATENCY_MS"):
        encode_payload(
            run_date=RUN_DATE,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            criteria={"MIN_ONLINE_DAYS": 5, "MIN_SUBGRAPHS": 1, "MAX_BLOCKS_BEHIND": 50000},
            daily_rows=daily_rows,
            indexers_evaluated=1,
            indexers_eligible=1,
            days=select_days_to_publish(WINDOW_START, WINDOW_END, 1),
        )


@pytest.mark.parametrize(
    "indexer, expected_error",
    [("0xnothex", "not valid hex"), ("0x1234", "not 20 bytes")],
    ids=["non_hex_address", "wrong_length_address"],
)
def test_encode_payload_fails_on_malformed_addresses(indexer: str, expected_error: str):
    """
    Tests that a malformed address is rejected rather than shifting every field that follows it.
    """
    with pytest.raises(PayloadError, match=expected_error):
        encode_payload(
            run_date=RUN_DATE,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            criteria=CRITERIA,
            daily_rows=[_row("2026-09-25", indexer, query_attempts=1)],
            indexers_evaluated=1,
            indexers_eligible=0,
            days=select_days_to_publish(WINDOW_START, WINDOW_END, 1),
        )


def test_decode_payload_rejects_foreign_payloads():
    """
    Tests that data written to the DataEdge contract by anyone else is rejected, since its fallback
    accepts calls from any address.
    """
    with pytest.raises(PayloadError, match="magic"):
        decode_payload(b"\x00\x01somebody elses payload")


def test_decode_payload_rejects_an_unsupported_version():
    """
    Tests that a payload from a newer encoder is refused rather than misread.
    """
    future_version = PAYLOAD_MAGIC + _encode_varint(ENCODING_VERSION + 1)

    with pytest.raises(PayloadError, match="Unsupported encoding version"):
        decode_payload(future_version)


def test_decode_payload_rejects_an_unknown_message_tag():
    """
    Tests that an unrecognised message is refused rather than decoded as whatever follows it.
    """
    unknown_tag = PAYLOAD_MAGIC + _encode_varint(ENCODING_VERSION) + b"\x7f"

    with pytest.raises(PayloadError, match="Unknown message tag"):
        decode_payload(unknown_tag)


def test_decode_payload_reads_message_tags_as_varints():
    """
    Tests that a tag is read as a varint, as the wire format states, so a tag of 128 or more is not
    split into a 1-byte tag followed by a stray byte.
    """
    multi_byte_tag = PAYLOAD_MAGIC + _encode_varint(ENCODING_VERSION) + _encode_varint(300)

    with pytest.raises(PayloadError, match="Unknown message tag: 0x12c"):
        decode_payload(multi_byte_tag)


def test_encode_varint_rejects_values_wider_than_64_bits():
    """
    Tests that the encoder never writes a value a subgraph mapping could not hold in a u64.
    """
    with pytest.raises(PayloadError, match="wider than 64 bits"):
        _encode_varint(2**64)


@pytest.mark.parametrize(
    "encoded, message",
    [
        (b"\xff" * 9 + b"\x02", "does not fit in 64 bits"),
        (b"\x80" * 10 + b"\x00", "longer than 64 bits"),
    ],
    ids=["value_overflows", "too_many_bytes"],
)
def test_decode_varint_rejects_varints_wider_than_64_bits(encoded: bytes, message: str):
    """
    Tests that the decoder refuses a varint wider than the format allows instead of reading on.
    """
    with pytest.raises(PayloadError, match=message):
        _decode_varint(encoded, 0)
