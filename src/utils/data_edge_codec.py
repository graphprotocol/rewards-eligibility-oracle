"""
Binary codec for the eligibility metrics payload published to a DataEdge contract.

DataEdge accepts any calldata on its fallback function and re-emits it as a Log event, which a
subgraph decodes into entities. A payload carries the run's provenance, the criteria applied and the
per-day metrics for the most recent days of the analysis window; the subgraph accumulates the rolling
window from successive payloads.

Wire format (all integers are unsigned LEB128 varints of at most 64 bits, all days are days since
1970-01-01):

    payload  := magic(2 bytes) version(varint) message*
    message  := tag(varint) body

    tag 0x01 RunInfo  := run_day, window_start_day, window_end_day,
                         indexers_evaluated, indexers_eligible
    tag 0x02 Criteria := min_online_days, min_subgraphs, max_latency_ms, max_blocks_behind
    tag 0x03 DailyMetrics := day, row_count, row*
        row  := address(20 bytes), query_attempts, qualifying_queries, qualifying_subgraphs,
                failed_status, failed_latency, failed_blocks_behind, is_online_day

Rows are emitted only for indexers that received query attempts that day, so an indexer absent from a
day's rows was routed nothing on it. A day on which nobody served anything is omitted altogether,
since that means its source data has not arrived rather than that the whole network was idle.

Nothing here enumerates the indexers a run evaluated: an indexer routed nothing across the whole
window appears in no payload at all, and only a consumer holding its own roster can tell that apart
from an indexer that does not exist. Criteria are published on every payload rather than on change,
so a payload is interpretable without any prior state.
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Mapping, Sequence, Tuple

logger = logging.getLogger(__name__)

# Identifies a payload as belonging to this oracle, so a subgraph can ignore anything else sent to
# the DataEdge contract, whose fallback accepts calls from any address
PAYLOAD_MAGIC = b"RE"

# Bumping this signals a breaking change to decoders; a payload carries exactly one version
ENCODING_VERSION = 1

# Message tags
TAG_RUN_INFO = 0x01
TAG_CRITERIA = 0x02
TAG_DAILY_METRICS = 0x03

# Criteria keys, in the order they appear on the wire
CRITERIA_FIELDS = ["MIN_ONLINE_DAYS", "MIN_SUBGRAPHS", "MAX_LATENCY_MS", "MAX_BLOCKS_BEHIND"]

# Per-indexer counters, in the order they appear on the wire
ROW_FIELDS = [
    "query_attempts",
    "qualifying_queries",
    "qualifying_subgraphs",
    "failed_status",
    "failed_latency",
    "failed_blocks_behind",
    "is_online_day",
]

# Day zero for the varint day encoding
EPOCH = date(1970, 1, 1)

# Length of an EVM address in bytes
ADDRESS_LENGTH = 20

# Largest value a varint may carry, so a subgraph mapping can decode every integer into a u64
MAX_VARINT_VALUE = 2**64 - 1


class PayloadError(Exception):
    """Raised when a payload cannot be encoded or decoded."""


def _encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as an unsigned LEB128 varint."""
    if value < 0:
        raise PayloadError(f"Cannot encode negative value as a varint: {value}")

    if value > MAX_VARINT_VALUE:
        raise PayloadError(f"Cannot encode a value wider than 64 bits as a varint: {value}")

    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(encoded)


def _decode_varint(payload: bytes, offset: int) -> Tuple[int, int]:
    """Decode the varint starting at offset, returning the value and the offset after it."""
    value = 0
    shift = 0

    while True:
        if offset >= len(payload):
            raise PayloadError("Payload ended in the middle of a varint")

        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if value > MAX_VARINT_VALUE:
            raise PayloadError("Varint does not fit in 64 bits")

        if not byte & 0x80:
            return value, offset

        shift += 7
        if shift > 63:
            raise PayloadError("Varint is longer than 64 bits")


def _encode_address(address: str) -> bytes:
    """Encode a hex indexer address as 20 raw bytes."""
    try:
        encoded = bytes.fromhex(address[2:] if address.lower().startswith("0x") else address)

    except ValueError as e:
        raise PayloadError(f"Indexer address is not valid hex: {address}") from e

    if len(encoded) != ADDRESS_LENGTH:
        raise PayloadError(f"Indexer address is not {ADDRESS_LENGTH} bytes: {address}")

    return encoded


def _encode_day(day: date) -> bytes:
    """Encode a date as days since the epoch."""
    return _encode_varint((day - EPOCH).days)


def _decode_day(payload: bytes, offset: int) -> Tuple[date, int]:
    """Decode a date stored as days since the epoch."""
    days, offset = _decode_varint(payload, offset)
    try:
        day = EPOCH + timedelta(days=days)
    except OverflowError as e:
        raise PayloadError("Encoded day is outside the supported date range") from e
    return day, offset


def select_days_to_publish(window_start: date, window_end: date, publish_days: int) -> List[date]:
    """
    Return the most recent days of the window that a run publishes, oldest first.

    A run at 10:00 UTC only sees part of its final day, so that day is published again by the
    following run. Publishing an overlap of more than one day also lets a run restate days whose
    source data arrived late, and lets it cover a day whose own run failed.

    Never reaches back past window_start, however many days are asked for. The clamp lives here so
    that every caller agrees on which days a run publishes.

    Args:
        window_start: First day of the analysis window
        window_end: Last day of the analysis window
        publish_days: How many trailing days to publish

    Returns:
        List[date]: The days to publish, oldest first
    """
    if publish_days < 1:
        raise PayloadError(f"publish_days must be at least 1, got {publish_days}")

    days_in_window = (window_end - window_start).days + 1
    if days_in_window < 1:
        raise PayloadError(f"window_end {window_end} is before window_start {window_start}")

    return [window_end - timedelta(days=offset) for offset in reversed(range(min(publish_days, days_in_window)))]


def encode_payload(
    run_date: date,
    window_start: date,
    window_end: date,
    criteria: Mapping[str, Any],
    daily_rows: Sequence[Mapping[str, Any]],
    indexers_evaluated: int,
    indexers_eligible: int,
    publish_days: int,
) -> bytes:
    """
    Encode a run's provenance, criteria and recent per-day metrics into a DataEdge payload.

    Args:
        run_date: The date of the run
        window_start: First day of the analysis window
        window_end: Last day of the analysis window
        criteria: Eligibility thresholds applied by this run, keyed by CRITERIA_FIELDS
        daily_rows: Per-indexer, per-day metric rows, each carrying 'day', 'indexer' and ROW_FIELDS
        indexers_evaluated: Number of indexers the run considered
        indexers_eligible: Number of indexers the run found eligible
        publish_days: How many trailing days of the window to publish

    Returns:
        bytes: The payload to send as calldata
    """
    payload = bytearray(PAYLOAD_MAGIC)
    payload += _encode_varint(ENCODING_VERSION)

    # Provenance, so a consumer can tell which run and window a payload describes
    payload += _encode_varint(TAG_RUN_INFO)
    payload += _encode_day(run_date)
    payload += _encode_day(window_start)
    payload += _encode_day(window_end)
    payload += _encode_varint(indexers_evaluated)
    payload += _encode_varint(indexers_eligible)

    # Thresholds, without which is_online_day cannot be interpreted
    payload += _encode_varint(TAG_CRITERIA)
    for field in CRITERIA_FIELDS:
        value = criteria.get(field)
        if value is None:
            raise PayloadError(f"Criteria is missing {field}")

        payload += _encode_varint(int(value))

    # Group the rows by day so each published day becomes one message
    rows_by_day: Dict[str, List[Mapping[str, Any]]] = {}
    for row in daily_rows:
        rows_by_day.setdefault(str(row["day"]), []).append(row)

    for day in select_days_to_publish(window_start, window_end, publish_days):
        # Skip indexers routed nothing that day; their absence is what encodes the zero row
        rows = [row for row in rows_by_day.get(day.isoformat(), []) if int(row["query_attempts"]) > 0]

        # A day nobody served is a day whose source data has not arrived, so it is omitted rather than
        # published as every indexer having been routed nothing. A later run publishes it once it has
        # data, while the window still reaches back to it.
        if not rows:
            continue

        payload += _encode_varint(TAG_DAILY_METRICS)
        payload += _encode_day(day)
        payload += _encode_varint(len(rows))

        for row in sorted(rows, key=lambda r: str(r["indexer"]).lower()):
            payload += _encode_address(str(row["indexer"]))
            for field in ROW_FIELDS:
                payload += _encode_varint(int(row[field]))

    return bytes(payload)


def decode_payload(payload: bytes) -> Dict[str, Any]:
    """
    Decode a DataEdge payload back into its messages.

    This mirrors what a subgraph mapping does and exists so the encoding can be asserted on directly,
    and so an operator can inspect what a run actually published.

    Args:
        payload: The raw calldata emitted by the DataEdge contract

    Returns:
        Dict[str, Any]: The decoded version, run info, criteria and per-day metrics
    """
    if not payload.startswith(PAYLOAD_MAGIC):
        raise PayloadError("Payload does not carry the expected magic bytes")

    offset = len(PAYLOAD_MAGIC)
    version, offset = _decode_varint(payload, offset)
    if version != ENCODING_VERSION:
        raise PayloadError(f"Unsupported encoding version: {version}")

    decoded: Dict[str, Any] = {"version": version, "run_info": None, "criteria": None, "daily_metrics": []}

    while offset < len(payload):
        tag, offset = _decode_varint(payload, offset)

        if tag == TAG_RUN_INFO:
            run_day, offset = _decode_day(payload, offset)
            window_start, offset = _decode_day(payload, offset)
            window_end, offset = _decode_day(payload, offset)
            indexers_evaluated, offset = _decode_varint(payload, offset)
            indexers_eligible, offset = _decode_varint(payload, offset)
            decoded["run_info"] = {
                "run_date": run_day,
                "window_start": window_start,
                "window_end": window_end,
                "indexers_evaluated": indexers_evaluated,
                "indexers_eligible": indexers_eligible,
            }

        elif tag == TAG_CRITERIA:
            criteria = {}
            for field in CRITERIA_FIELDS:
                criteria[field], offset = _decode_varint(payload, offset)
            decoded["criteria"] = criteria

        elif tag == TAG_DAILY_METRICS:
            day, offset = _decode_day(payload, offset)
            row_count, offset = _decode_varint(payload, offset)

            rows = []
            for _ in range(row_count):
                if offset + ADDRESS_LENGTH > len(payload):
                    raise PayloadError("Payload ended in the middle of an indexer address")

                row: Dict[str, Any] = {"indexer": "0x" + payload[offset : offset + ADDRESS_LENGTH].hex()}
                offset += ADDRESS_LENGTH
                for field in ROW_FIELDS:
                    row[field], offset = _decode_varint(payload, offset)
                rows.append(row)

            decoded["daily_metrics"].append({"day": day, "rows": rows})

        else:
            raise PayloadError(f"Unknown message tag: {hex(tag)}")

    return decoded
