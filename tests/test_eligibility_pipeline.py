"""
Unit tests for the EligibilityPipeline.
"""

import logging
import os
import shutil
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List

import pandas as pd
import pytest
from pytest import FixtureRequest

from src.models.eligibility_pipeline import EligibilityPipeline

# --- Fixtures ---


@pytest.fixture
def pipeline(tmp_path: Path) -> EligibilityPipeline:
    """Provides an EligibilityPipeline instance using a temporary directory."""
    return EligibilityPipeline(project_root=tmp_path)


@pytest.fixture
def sample_data() -> pd.DataFrame:
    """Provides a sample DataFrame with a mix of eligible and ineligible indexers."""
    return pd.DataFrame({"indexer": ["0x1", "0x2", "0x3", "0x4"], "eligible_for_indexing_rewards": [1, 0, 1, 0]})


@pytest.fixture
def all_eligible_data() -> pd.DataFrame:
    """Provides a sample DataFrame where all indexers are eligible."""
    return pd.DataFrame({"indexer": ["0x1", "0x3"], "eligible_for_indexing_rewards": [1, 1]})


@pytest.fixture
def all_ineligible_data() -> pd.DataFrame:
    """Provides a sample DataFrame where all indexers are ineligible."""
    return pd.DataFrame({"indexer": ["0x2", "0x4"], "eligible_for_indexing_rewards": [0, 0]})


@pytest.fixture
def empty_data() -> pd.DataFrame:
    """Provides an empty DataFrame with the correct structure."""
    return pd.DataFrame({"indexer": [], "eligible_for_indexing_rewards": []}).astype(
        {"eligible_for_indexing_rewards": int}
    )


@pytest.fixture
def mixed_value_data() -> pd.DataFrame:
    """Provides a sample DataFrame with various values in the eligibility column."""
    return pd.DataFrame(
        {
            "indexer": ["0x1", "0x2", "0x3", "0x4", "0x5"],
            # Includes valid (1, 0), invalid (2, -1), and null values
            "eligible_for_indexing_rewards": [1, 0, 2, -1, None],
        }
    )


@pytest.fixture
def float_value_data() -> pd.DataFrame:
    """Provides a sample DataFrame with floating-point values in the eligibility column."""
    return pd.DataFrame(
        {
            "indexer": ["0x1", "0x2", "0x3", "0x4"],
            "eligible_for_indexing_rewards": [1.0, 0.0, 1.0, 0.0],
        }
    )


@pytest.fixture
def duplicate_indexer_data() -> pd.DataFrame:
    """Provides a sample DataFrame with duplicate indexer entries."""
    return pd.DataFrame(
        {
            "indexer": ["0x1", "0x2", "0x1", "0x3"],
            "eligible_for_indexing_rewards": [1, 0, 1, 1],
        }
    )


@pytest.fixture
def non_numeric_data() -> pd.DataFrame:
    """Provides a sample DataFrame with non-numeric values in the eligibility column."""
    return pd.DataFrame(
        {
            "indexer": ["0x1", "0x2", "0x3"],
            # Use strings for all values to ensure consistent types after CSV I/O
            "eligible_for_indexing_rewards": ["1", "invalid", "0"],
        }
    )


# --- Test Helpers ---


def _assert_output_files(
    pipeline: EligibilityPipeline,
    current_date: date,
    original_data: pd.DataFrame,
    expected_eligible: List[str],
    expected_ineligible: List[str],
) -> None:
    """Helper to assert file creation and content."""
    output_dir = pipeline.get_date_output_directory(current_date)
    raw_path = output_dir / "indexer_issuance_eligibility_data.csv"
    eligible_path = output_dir / "eligible_indexers.csv"
    ineligible_path = output_dir / "ineligible_indexers.csv"

    assert raw_path.exists(), "Raw data file was not created."
    assert eligible_path.exists(), "Eligible indexers file was not created."
    assert ineligible_path.exists(), "Ineligible indexers file was not created."

    # Verify content of the created files
    raw_df = pd.read_csv(raw_path)
    eligible_df = pd.read_csv(eligible_path)
    ineligible_df = pd.read_csv(ineligible_path)

    pd.testing.assert_frame_equal(raw_df, original_data, check_dtype=False)
    assert sorted(eligible_df["indexer"].tolist()) == sorted(expected_eligible)
    assert sorted(ineligible_df["indexer"].tolist()) == sorted(expected_ineligible)


def _stat_raising_for(bad_name: str):
    """Builds a Path.stat replacement that simulates one specific file disappearing mid-check."""
    real_stat = Path.stat


    def _stat(self: Path, *args, **kwargs):
        if self.name == bad_name:
            raise FileNotFoundError(f"simulated race condition for {bad_name}")

        return real_stat(self, *args, **kwargs)

    return _stat


# --- Tests for process() ---


@pytest.mark.parametrize(
    "input_data_fixture, expected_eligible, expected_ineligible",
    [
        ("sample_data", ["0x1", "0x3"], ["0x2", "0x4"]),
        ("all_eligible_data", ["0x1", "0x3"], []),
        ("all_ineligible_data", [], ["0x2", "0x4"]),
        ("empty_data", [], []),
        ("mixed_value_data", ["0x1"], ["0x2", "0x3", "0x4", "0x5"]),
        ("float_value_data", ["0x1", "0x3"], ["0x2", "0x4"]),
        ("duplicate_indexer_data", ["0x1", "0x1", "0x3"], ["0x2"]),
        ("non_numeric_data", ["0x1"], ["0x2", "0x3"]),
    ],
    ids=[
        "mixed_eligibility",
        "all_eligible",
        "all_ineligible",
        "empty_dataframe",
        "data_with_unexpected_values",
        "float_values_for_eligibility",
        "data_with_duplicate_indexers",
        "data_with_non_numeric_values",
    ],
)
def test_process_filters_and_saves_data_correctly(
    pipeline: EligibilityPipeline,
    input_data_fixture: str,
    expected_eligible: List[str],
    expected_ineligible: List[str],
    request: FixtureRequest,
):
    """
    Tests that `process` correctly separates indexers based on eligibility
    and creates the expected output files with correct content.
    """
    # Arrange
    input_data = request.getfixturevalue(input_data_fixture)
    current_date_val = date.today()

    # Act
    eligible, ineligible = pipeline.process(input_data, current_date=current_date_val)

    # Assert: Check returned lists for correctness
    assert sorted(eligible) == sorted(expected_eligible)
    assert sorted(ineligible) == sorted(expected_ineligible)

    # Assert: Check that files are created and have the correct content
    _assert_output_files(pipeline, current_date_val, input_data, expected_eligible, expected_ineligible)


def test_process_fails_on_invalid_dataframe_structure(pipeline: EligibilityPipeline):
    """
    Tests that `process` correctly raises a ValueError when the input DataFrame
    is missing required columns.
    """
    # Arrange
    invalid_df = pd.DataFrame({"indexer_id": ["0x1"]})  # Missing 'indexer'

    # Act & Assert
    with pytest.raises(ValueError, match="DataFrame missing required columns"):
        pipeline.process(invalid_df, current_date=date.today())


def test_process_fails_on_none_input(pipeline: EligibilityPipeline):
    """
    Tests that `process` raises an AttributeError when the input is not a DataFrame,
    as it will fail when trying to access attributes like `columns`.
    """
    # Arrange
    invalid_input = None

    # Act & Assert
    with pytest.raises(AttributeError):
        pipeline.process(invalid_input, current_date=date.today())


# --- Tests for clean_old_date_directories() ---


@pytest.mark.parametrize(
    "max_age, days_to_create, expected_to_exist, expected_to_be_deleted",
    [
        (30, [30, 31], [30], [31]),  # Standard case
        (0, [0, 1], [0], [1]),  # Boundary case: zero max_age
        (30, [1, 15, 29], [1, 15, 29], []),  # All recent
        (-1, [30, 31], [30, 31], []),  # Negative max_age should not delete anything
    ],
    ids=["standard_cleanup", "zero_max_age", "all_recent_are_kept", "negative_max_age_keeps_all"],
)
def test_clean_old_date_directories_removes_correct_directories(
    pipeline: EligibilityPipeline, max_age, days_to_create, expected_to_exist, expected_to_be_deleted
):
    """
    Tests `clean_old_date_directories` correctly removes old directories
    while preserving recent ones based on `max_age_before_deletion`.
    """
    # Arrange
    today = date.today()
    dirs_to_create = {
        day: pipeline.get_date_output_directory(today - timedelta(days=day)) for day in days_to_create
    }
    for d in dirs_to_create.values():
        d.mkdir(parents=True)
        # Add a dummy file to ensure rmtree on non-empty dirs is tested
        (d / "dummy_file.txt").touch()

    # Act
    pipeline.clean_old_date_directories(max_age_before_deletion=max_age)

    # Assert
    for day in expected_to_exist:
        assert dirs_to_create[day].exists(), f"Directory for {day} days ago should exist."
    for day in expected_to_be_deleted:
        assert not dirs_to_create[day].exists(), f"Directory for {day} days ago should have been deleted."


def test_clean_old_date_directories_ignores_malformed_names(pipeline: EligibilityPipeline):
    """
    Tests that `clean_old_date_directories` ignores directories with names that
    are not in date format and also ignores loose files.
    """
    # Arrange
    max_age = 30
    old_date = date.today() - timedelta(days=max_age + 1)

    # Create directories and a file to test against
    old_dir_to_be_deleted = pipeline.get_date_output_directory(old_date)
    malformed_dir = pipeline.output_dir / "not-a-date"
    some_file = pipeline.output_dir / "some-file.txt"

    old_dir_to_be_deleted.mkdir(parents=True)
    malformed_dir.mkdir(parents=True)
    some_file.touch()

    # Act
    pipeline.clean_old_date_directories(max_age_before_deletion=max_age)

    # Assert
    assert not old_dir_to_be_deleted.exists()
    assert malformed_dir.exists()
    assert some_file.exists()


def test_clean_old_date_directories_handles_missing_output_dir(
    pipeline: EligibilityPipeline, caplog: pytest.LogCaptureFixture
):
    """
    Tests that `clean_old_date_directories` runs without errors and logs a
    warning if the main output directory does not exist.
    """
    # This test passes if no exception is raised
    with caplog.at_level(logging.WARNING):
        pipeline.clean_old_date_directories(max_age_before_deletion=30)
    assert "Output directory does not exist" in caplog.text


# --- Tests for get_date_output_directory() ---


def test_get_date_output_directory_returns_correct_path_format(pipeline: EligibilityPipeline):
    """
    Tests that `get_date_output_directory` returns a correctly formatted
    path for a given date.
    """
    # Arrange
    test_date = date(2023, 10, 26)
    expected_path = pipeline.output_dir / "2023-10-26"

    # Act
    actual_path = pipeline.get_date_output_directory(test_date)

    # Assert
    assert actual_path == expected_path


# --- Tests for validate_dataframe_structure() ---


@pytest.mark.parametrize(
    "df_data, required_cols, should_raise",
    [
        ({"col1": [1], "col2": [2]}, ["col1", "col2"], False),
        ({"col1": [1]}, ["col1", "col2"], True),
        ({}, ["col1"], True),
    ],
    ids=["valid_structure", "missing_one_column", "empty_with_missing_column"],
)
def test_validate_dataframe_structure_validates_correctly(
    pipeline: EligibilityPipeline, df_data: dict, required_cols: List[str], should_raise: bool
):
    """
    Tests that `validate_dataframe_structure` correctly validates or raises
    ValueError for different DataFrame structures.
    """
    # Arrange
    df = pd.DataFrame(df_data)

    # Act & Assert
    if should_raise:
        with pytest.raises(ValueError, match="DataFrame missing required columns"):
            pipeline.validate_dataframe_structure(df, required_columns=required_cols)
    else:
        assert pipeline.validate_dataframe_structure(df, required_columns=required_cols) is True


# --- Tests for get_directory_size_info() ---


def test_get_directory_size_info_succeeds_with_content(pipeline: EligibilityPipeline):
    """
    Tests `get_directory_size_info` for a directory with files and subdirectories.
    """
    # Arrange
    output_dir = pipeline.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "subdir").mkdir()
    (output_dir / "file1.txt").write_text("hello")
    (output_dir / "subdir" / "file2.txt").write_text("world")

    # Act
    info = pipeline.get_directory_size_info()

    # Assert
    assert info["exists"] is True
    assert info["total_size_bytes"] == 10
    assert info["total_size_mb"] == 0.0
    assert info["directory_count"] == 1
    assert info["file_count"] == 2
    assert info["path"] == str(output_dir)


def test_get_directory_size_info_succeeds_for_empty_directory(pipeline: EligibilityPipeline):
    """
    Tests `get_directory_size_info` for an empty directory.
    """
    # Arrange
    output_dir = pipeline.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Act
    info = pipeline.get_directory_size_info()

    # Assert
    assert info["exists"] is True
    assert info["total_size_bytes"] == 0
    assert info["directory_count"] == 0
    assert info["file_count"] == 0


def test_get_directory_size_info_succeeds_for_non_existent_directory(pipeline: EligibilityPipeline):
    """
    Tests `get_directory_size_info` for a directory that does not exist.
    """
    # Arrange: The `pipeline` fixture creates a root tmp_path, but `output_dir`
    # inside it doesn't exist yet until mkdir is called. We'll ensure it's gone.
    if pipeline.output_dir.exists():
        shutil.rmtree(pipeline.output_dir)

    # Act
    info = pipeline.get_directory_size_info()

    # Assert
    assert info["exists"] is False
    assert info["total_size_bytes"] == 0
    assert info["directory_count"] == 0
    assert info["file_count"] == 0


def test_get_directory_size_info_calculates_megabytes_correctly(pipeline: EligibilityPipeline):
    """
    Tests `get_directory_size_info` correctly calculates size in megabytes.
    """
    # Arrange
    output_dir = pipeline.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    # Create a file of approx 2.5 MB
    large_file_content = b"\0" * (1024 * 1024 * 2 + 1024 * 512)
    (output_dir / "large_file.bin").write_bytes(large_file_content)

    # Act
    info = pipeline.get_directory_size_info()

    # Assert
    assert info["exists"] is True
    assert info["total_size_bytes"] == len(large_file_content)
    assert info["total_size_mb"] == 2.5
    assert info["file_count"] == 1
    assert info["directory_count"] == 0
    assert info["path"] == str(output_dir)


# --- Tests for clean_old_date_directories() race condition ---


def test_clean_old_date_directories_continues_when_rmtree_fails(pipeline: EligibilityPipeline, mocker):
    """
    Tests that `clean_old_date_directories` skips a directory whose rmtree
    fails (e.g. already removed by another process) and still removes the rest.
    """
    # Arrange
    today = date.today()
    doomed = pipeline.get_date_output_directory(today - timedelta(days=40))
    also_old = pipeline.get_date_output_directory(today - timedelta(days=35))
    for d in (doomed, also_old):
        d.mkdir(parents=True)
        (d / "dummy_file.txt").touch()

    mocker.patch(
        "src.models.eligibility_pipeline.shutil.rmtree",
        side_effect=[OSError("already removed"), None],
    )

    # Act & Assert: should not raise despite the first rmtree failing
    pipeline.clean_old_date_directories(max_age_before_deletion=30)


# --- Tests for has_existing_processed_data() ---


REQUIRED_OUTPUT_FILES = [
    "eligible_indexers.csv",
    "indexer_issuance_eligibility_data.csv",
    "ineligible_indexers.csv",
]


@pytest.mark.parametrize(
    "files_to_create, expected_result",
    [
        ([], False),
        (["eligible_indexers.csv"], False),
        (REQUIRED_OUTPUT_FILES, True),
    ],
    ids=["missing_directory", "missing_some_files", "all_files_present"],
)
def test_has_existing_processed_data_checks_completeness(
    pipeline: EligibilityPipeline, files_to_create: List[str], expected_result: bool
):
    """
    Tests that `has_existing_processed_data` returns True only when the
    date directory exists and all required, non-empty files are present.
    """
    # Arrange
    current_date_val = date.today()
    if files_to_create:
        output_dir = pipeline.get_date_output_directory(current_date_val)
        output_dir.mkdir(parents=True)
        for name in files_to_create:
            (output_dir / name).write_text("data")

    # Act & Assert
    assert pipeline.has_existing_processed_data(current_date_val) is expected_result


def test_has_existing_processed_data_returns_false_for_empty_file(pipeline: EligibilityPipeline):
    """
    Tests that `has_existing_processed_data` treats a present-but-empty
    required file as missing data.
    """
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    for name in REQUIRED_OUTPUT_FILES:
        (output_dir / name).touch()

    # Act & Assert
    assert pipeline.has_existing_processed_data(current_date_val) is False


def test_has_existing_processed_data_handles_file_disappearing_mid_check(pipeline: EligibilityPipeline, mocker):
    """
    Tests that `has_existing_processed_data` returns False, rather than
    raising, when a file vanishes between the exists() and stat() calls.
    """
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    for name in REQUIRED_OUTPUT_FILES:
        (output_dir / name).write_text("data")

    mocker.patch.object(Path, "stat", _stat_raising_for("eligible_indexers.csv"))

    # Act & Assert
    assert pipeline.has_existing_processed_data(current_date_val) is False


# --- Tests for get_data_age_minutes() ---


def test_get_data_age_minutes_raises_when_directory_missing(pipeline: EligibilityPipeline):
    """Tests that `get_data_age_minutes` raises FileNotFoundError when the date directory doesn't exist."""
    # Act & Assert
    with pytest.raises(FileNotFoundError, match="No data directory found"):
        pipeline.get_data_age_minutes(date.today())


def test_get_data_age_minutes_raises_when_no_csv_files(pipeline: EligibilityPipeline):
    """Tests that `get_data_age_minutes` raises FileNotFoundError when the directory has no CSV files."""
    # Arrange
    output_dir = pipeline.get_date_output_directory(date.today())
    output_dir.mkdir(parents=True)
    (output_dir / "notes.txt").touch()

    # Act & Assert
    with pytest.raises(FileNotFoundError, match="No CSV files found"):
        pipeline.get_data_age_minutes(date.today())


def test_get_data_age_minutes_uses_oldest_file(pipeline: EligibilityPipeline):
    """
    Tests that `get_data_age_minutes` calculates age from the oldest CSV
    file, not the newest, to be conservative about freshness.
    """
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    older, newer = output_dir / "older.csv", output_dir / "newer.csv"
    older.write_text("data")
    newer.write_text("data")
    ten_minutes_ago = time.time() - 600
    os.utime(older, (ten_minutes_ago, ten_minutes_ago))

    # Act
    age = pipeline.get_data_age_minutes(current_date_val)

    # Assert
    assert age == pytest.approx(10.0, abs=0.1)


def test_get_data_age_minutes_skips_files_that_disappear(pipeline: EligibilityPipeline, mocker):
    """
    Tests that `get_data_age_minutes` skips a file that vanishes between
    glob() and stat(), still computing age from the remaining files.
    """
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    (output_dir / "stable.csv").write_text("data")
    (output_dir / "flaky.csv").write_text("data")

    mocker.patch.object(Path, "stat", _stat_raising_for("flaky.csv"))

    # Act & Assert
    assert pipeline.get_data_age_minutes(current_date_val) >= 0


def test_get_data_age_minutes_raises_when_all_files_disappear(pipeline: EligibilityPipeline, mocker):
    """
    Tests that `get_data_age_minutes` raises FileNotFoundError when every
    CSV file vanishes during the age calculation.
    """
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    (output_dir / "a.csv").write_text("data")

    mocker.patch.object(Path, "stat", side_effect=FileNotFoundError("vanished"))

    # Act & Assert
    with pytest.raises(FileNotFoundError, match="All CSV files disappeared"):
        pipeline.get_data_age_minutes(current_date_val)


# --- Tests for has_fresh_processed_data() ---


def test_has_fresh_processed_data_returns_false_when_no_existing_data(pipeline: EligibilityPipeline):
    """Tests that `has_fresh_processed_data` short-circuits to False when data doesn't exist yet."""
    # Act & Assert
    assert pipeline.has_fresh_processed_data(date.today()) is False


def test_has_fresh_processed_data_returns_true_when_recently_written(pipeline: EligibilityPipeline):
    """Tests that `has_fresh_processed_data` returns True for data written moments ago."""
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    for name in REQUIRED_OUTPUT_FILES:
        (output_dir / name).write_text("data")

    # Act & Assert
    assert pipeline.has_fresh_processed_data(current_date_val, max_age_minutes=30) is True


@pytest.mark.parametrize(
    "data_age_minutes, max_age_minutes, expected",
    [
        (29.9, 30, True),
        (30.0, 30, True),
        (30.1, 30, False),
    ],
    ids=["just_within_window", "exactly_at_boundary", "just_past_boundary"],
)
def test_has_fresh_processed_data_respects_max_age(
    pipeline: EligibilityPipeline, mocker, data_age_minutes: float, max_age_minutes: int, expected: bool
):
    """
    Tests that `has_fresh_processed_data` correctly compares data age
    against the max_age_minutes threshold, including the inclusive boundary.
    Mocks `get_data_age_minutes` directly to avoid flaky real-clock timing.
    """
    # Arrange
    mocker.patch.object(EligibilityPipeline, "has_existing_processed_data", return_value=True)
    mocker.patch.object(EligibilityPipeline, "get_data_age_minutes", return_value=data_age_minutes)

    # Act & Assert
    assert pipeline.has_fresh_processed_data(date.today(), max_age_minutes=max_age_minutes) is expected


def test_has_fresh_processed_data_handles_race_condition_gracefully(pipeline: EligibilityPipeline, mocker):
    """
    Tests that `has_fresh_processed_data` returns False, rather than
    raising, if data disappears between the existence check and the age
    calculation.
    """
    # Arrange
    mocker.patch.object(EligibilityPipeline, "has_existing_processed_data", return_value=True)
    mocker.patch.object(EligibilityPipeline, "get_data_age_minutes", side_effect=FileNotFoundError("vanished"))

    # Act & Assert
    assert pipeline.has_fresh_processed_data(date.today()) is False


# --- Tests for load_eligible_indexers_from_csv() ---


def test_load_eligible_indexers_from_csv_raises_when_missing(pipeline: EligibilityPipeline):
    """Tests that `load_eligible_indexers_from_csv` raises FileNotFoundError when the CSV doesn't exist."""
    # Act & Assert
    with pytest.raises(FileNotFoundError, match="Eligible indexers CSV not found"):
        pipeline.load_eligible_indexers_from_csv(date.today())


def test_load_eligible_indexers_from_csv_returns_addresses(pipeline: EligibilityPipeline):
    """Tests that `load_eligible_indexers_from_csv` returns the indexer addresses from a valid CSV."""
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    (output_dir / "eligible_indexers.csv").write_text("indexer\n0x1\n0x2\n")

    # Act & Assert
    assert pipeline.load_eligible_indexers_from_csv(current_date_val) == ["0x1", "0x2"]


def test_load_eligible_indexers_from_csv_returns_empty_list_for_header_only(pipeline: EligibilityPipeline):
    """Tests that `load_eligible_indexers_from_csv` returns an empty list for a header-only CSV."""
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    (output_dir / "eligible_indexers.csv").write_text("indexer\n")

    # Act & Assert
    assert pipeline.load_eligible_indexers_from_csv(current_date_val) == []


def test_load_eligible_indexers_from_csv_raises_when_column_missing(pipeline: EligibilityPipeline):
    """Tests that `load_eligible_indexers_from_csv` raises ValueError when the 'indexer' column is absent."""
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    (output_dir / "eligible_indexers.csv").write_text("wrong_column\n0x1\n")

    # Act & Assert
    with pytest.raises(ValueError, match="missing 'indexer' column"):
        pipeline.load_eligible_indexers_from_csv(current_date_val)


def test_load_eligible_indexers_from_csv_wraps_parse_errors(pipeline: EligibilityPipeline, mocker):
    """Tests that `load_eligible_indexers_from_csv` wraps CSV parsing failures in a ValueError."""
    # Arrange
    current_date_val = date.today()
    output_dir = pipeline.get_date_output_directory(current_date_val)
    output_dir.mkdir(parents=True)
    (output_dir / "eligible_indexers.csv").write_text("indexer\n0x1\n")

    mocker.patch("pandas.read_csv", side_effect=pd.errors.ParserError("bad token"))

    # Act & Assert
    with pytest.raises(ValueError, match="Error reading CSV file"):
        pipeline.load_eligible_indexers_from_csv(current_date_val)
