"""
Lock Manager utility for preventing multiple Service Quality Oracle instances from running simultaneously.

Uses file-based locking (fcntl) that works for both Docker Compose (single host) and Kubernetes (via PVC).
"""

import fcntl
import logging
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when lock cannot be acquired because another instance holds it"""

    pass


class LockManager:
    """
    Context manager for file-based instance locking.

    Uses fcntl.flock() to ensure only one scheduler instance runs at a time.
    Works across processes on the same filesystem (local mounts and most network filesystems).

    Example:
        with LockManager():
            # Only one instance can execute this block
            run_scheduler()
    """

    def __init__(self, lock_file_path: Optional[Path] = None):
        """
        Initialize LockManager.

        Params:
            lock_file_path: Path to lock file. Defaults to /app/data/oracle.lock

        Raises:
            TypeError: If lock_file_path is not a Path object
        """
        # Fail fast - validate input type
        if lock_file_path is not None and not isinstance(lock_file_path, Path):
            raise TypeError(f"lock_file_path must be a Path object, got {type(lock_file_path).__name__}")

        self.lock_file_path = lock_file_path or Path("/app/data/oracle.lock")
        self.lock_file_handle = None


    def __enter__(self):
        """
        Acquire exclusive lock when entering context.

        Returns:
            Self

        Raises:
            LockAcquisitionError: If lock cannot be acquired
        """
        try:
            # Create parent directory if needed
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Open lock file
            self.lock_file_handle = open(self.lock_file_path, "w")

            # Attempt non-blocking exclusive lock
            fcntl.flock(self.lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write metadata to lock file
            self._write_lock_metadata()

            logger.info(f"Lock acquired successfully: {self.lock_file_path}")
            return self

        except BlockingIOError:
            # Lock is held by another process
            holder_info = self.get_lock_holder_info()
            error_msg = f"Lock already held by another instance: {holder_info}"
            logger.error(error_msg)

            # Clean up file handle
            if self.lock_file_handle:
                self.lock_file_handle.close()
                self.lock_file_handle = None

            raise LockAcquisitionError(error_msg)

        except Exception as e:
            # Unexpected error during lock acquisition
            logger.error(f"Unexpected error acquiring lock: {e}", exc_info=True)

            # Clean up file handle
            if self.lock_file_handle:
                self.lock_file_handle.close()
                self.lock_file_handle = None

            raise


    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Release lock when exiting context.

        Lock is automatically released by OS when file is closed, but we explicitly
        release it here for clarity.

        Params:
            exc_type: Exception type if exception occurred
            exc_val: Exception value if exception occurred
            exc_tb: Exception traceback if exception occurred

        Returns:
            False to propagate exceptions
        """
        try:
            if self.lock_file_handle:
                # Release lock explicitly (though closing file will release it too)
                fcntl.flock(self.lock_file_handle.fileno(), fcntl.LOCK_UN)

                # Close file
                self.lock_file_handle.close()
                self.lock_file_handle = None

                logger.info(f"Lock released: {self.lock_file_path}")

        except Exception as e:
            logger.error(f"Error releasing lock: {e}", exc_info=True)

        # Return False to propagate any exceptions that occurred in the context
        return False


    def _write_lock_metadata(self):
        """Write PID, hostname, and timestamp to lock file for debugging"""
        try:
            metadata = (
                f"pid={os.getpid()}\n"
                f"hostname={socket.gethostname()}\n"
                f"timestamp={datetime.now().astimezone().isoformat()}\n"
            )

            self.lock_file_handle.write(metadata)
            self.lock_file_handle.flush()

        except Exception as e:
            logger.warning(f"Failed to write lock metadata: {e}")


    def get_lock_holder_info(self) -> Optional[dict]:
        """
        Get information about current lock holder.

        Returns:
            Dictionary with 'pid', 'hostname', 'timestamp' if lock file exists and is readable,
            None otherwise
        """
        try:
            if not self.lock_file_path.exists():
                return None

            content = self.lock_file_path.read_text()
            metadata = {}

            for line in content.strip().split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    metadata[key] = value

            return metadata

        except Exception as e:
            logger.warning(f"Failed to read lock holder info: {e}")
            return None
