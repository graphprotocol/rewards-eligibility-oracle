"""
Unit tests for the LockManager utility.
Tests file-based locking mechanism that prevents multiple instances from running simultaneously.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.utils.lock_manager import LockManager


class TestFileLock:
    """Test file-based locking mechanism"""


    @pytest.fixture
    def temp_lock_dir(self):
        """Create temporary directory for lock files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)


    def test_lock_acquisition_succeeds_when_available(self, temp_lock_dir):
        """Test that file lock can be acquired when available"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        lock_manager = LockManager(lock_file_path=lock_file)

        # Act
        with lock_manager:
            content = lock_file.read_text()

            # Assert
            assert lock_file.exists()
            assert f"pid={os.getpid()}" in content
            assert "hostname=" in content
            assert "timestamp=" in content


    def test_lock_acquisition_fails_when_already_held(self, temp_lock_dir):
        """Test that second instance cannot acquire lock when first instance holds it"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        first_lock = LockManager(lock_file_path=lock_file)
        second_lock = LockManager(lock_file_path=lock_file)

        # Act
        with first_lock:
            with pytest.raises(Exception) as exc_info:
                with second_lock:
                    pass

            # Assert
            assert "lock" in str(exc_info.value).lower() or "already" in str(exc_info.value).lower()


    def test_lock_released_on_context_manager_exit(self, temp_lock_dir):
        """Test that lock is released when context manager exits"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        first_lock = LockManager(lock_file_path=lock_file)
        second_lock = LockManager(lock_file_path=lock_file)

        # Act
        with first_lock:
            pass

        # Assert
        with second_lock:
            assert lock_file.exists()


    def test_stale_lock_cleanup_when_process_dead(self, temp_lock_dir):
        """Test that stale locks from dead processes are cleaned up"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        fake_dead_pid = 999999
        stale_content = f"pid={fake_dead_pid}\nhostname=old-host\ntimestamp=2025-01-01T00:00:00+00:00"
        lock_file.write_text(stale_content)
        lock_manager = LockManager(lock_file_path=lock_file)

        # Act
        with lock_manager:
            content = lock_file.read_text()

            # Assert
            assert f"pid={os.getpid()}" in content
            assert f"pid={fake_dead_pid}" not in content


    def test_lock_file_contains_correct_metadata(self, temp_lock_dir):
        """Test that lock file contains PID, hostname, and timestamp"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        lock_manager = LockManager(lock_file_path=lock_file)

        # Act
        with lock_manager:
            content = lock_file.read_text()
            lines = content.strip().split("\n")
            metadata = {}
            for line in lines:
                key, value = line.split("=", 1)
                metadata[key] = value

            # Assert
            assert len(lines) == 3
            assert "pid" in metadata
            assert metadata["pid"] == str(os.getpid())
            assert "hostname" in metadata
            assert len(metadata["hostname"]) > 0
            assert "timestamp" in metadata
            assert "T" in metadata["timestamp"]


    def test_lock_acquisition_creates_parent_directory(self, temp_lock_dir):
        """Test that lock acquisition creates parent directory if needed"""
        # Arrange
        nested_dir = temp_lock_dir / "subdir" / "nested"
        lock_file = nested_dir / "test.lock"
        lock_manager = LockManager(lock_file_path=lock_file)
        assert not nested_dir.exists()

        # Act
        with lock_manager:
            pass

        # Assert
        assert nested_dir.exists()
        assert lock_file.exists()


    def test_lock_released_on_exception(self, temp_lock_dir):
        """Test that lock is released even when exception occurs in context"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        first_lock = LockManager(lock_file_path=lock_file)
        second_lock = LockManager(lock_file_path=lock_file)

        # Act
        with pytest.raises(ValueError):
            with first_lock:
                raise ValueError("Test exception")

        # Assert
        with second_lock:
            assert lock_file.exists()


    def test_default_lock_file_path(self):
        """Test that default lock file path is /app/data/oracle.lock"""
        # Arrange & Act
        lock_manager = LockManager()

        # Assert
        assert lock_manager.lock_file_path == Path("/app/data/oracle.lock")


    def test_init_raises_type_error_for_invalid_path_type(self):
        """Test that LockManager fails fast when given non-Path lock_file_path"""
        # Arrange
        invalid_path = "/app/data/oracle.lock"  # String instead of Path

        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            LockManager(lock_file_path=invalid_path)

        assert "must be a Path object" in str(exc_info.value)
        assert "str" in str(exc_info.value)


    def test_get_lock_holder_info_returns_metadata(self, temp_lock_dir):
        """Test that get_lock_holder_info returns current lock holder metadata"""
        # Arrange
        lock_file = temp_lock_dir / "test.lock"
        first_lock = LockManager(lock_file_path=lock_file)
        second_lock = LockManager(lock_file_path=lock_file)

        # Act
        with first_lock:
            holder_info = second_lock.get_lock_holder_info()

            # Assert
            assert holder_info is not None
            assert "pid" in holder_info
            assert holder_info["pid"] == str(os.getpid())
            assert "hostname" in holder_info
            assert "timestamp" in holder_info
