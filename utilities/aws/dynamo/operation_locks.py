import time
import uuid
from . import BaseDynamoTable
from utilities.logging import get_logger

logger = get_logger(name="operation_locks")


class OperationLocksTable(BaseDynamoTable):
    """Operation locks table for preventing concurrent processes"""

    def __init__(self):
        super().__init__("operation_locks")

    def acquire_lock(self, operation_name, lock_id=None, lambda_request_id=None):
        """
        Acquire a lock for the given operation.
        Returns True if lock acquired, False if already locked.
        """
        if lock_id is None:
            lock_id = str(uuid.uuid4())

        try:
            # Use conditional put to ensure atomicity - only create if operation doesn't exist
            item_dict = {
                "operation_name": operation_name,
                "lock_id": lock_id,
                "created_at": int(time.time()),
                "status": "ACTIVE",
            }

            if lambda_request_id:
                item_dict["lambda_request_id"] = lambda_request_id

            success = self.conditional_put_item(
                item_dict=item_dict,
                condition_expression="attribute_not_exists(operation_name)",
            )

            if success:
                logger.info(
                    f"Lock acquired for operation: {operation_name}, lock_id: {lock_id}"
                )
                return lock_id
            else:
                logger.info(f"Lock already exists for operation: {operation_name}")
                return None

        except Exception as e:
            logger.exception(
                f"Error acquiring lock for operation {operation_name}: {e}"
            )
            return None

    def release_lock(self, operation_name, lock_id):
        """
        Release a lock for the given operation.
        Only releases if the lock_id matches the current lock.
        """
        try:
            # First verify the lock belongs to this process
            current_lock = self.get_item({"operation_name": operation_name})

            if not current_lock:
                logger.warning(f"No lock found for operation: {operation_name}")
                return True  # Consider it released

            current_lock_id = current_lock.get("lock_id", {}).get("S")
            if current_lock_id != lock_id:
                logger.warning(
                    f"Lock ID mismatch for operation {operation_name}. Expected: {lock_id}, Found: {current_lock_id}"
                )
                return False

            # Delete the lock
            success = self.delete_item({"operation_name": operation_name})

            if success:
                logger.info(
                    f"Lock released for operation: {operation_name}, lock_id: {lock_id}"
                )

            return success

        except Exception as e:
            logger.exception(
                f"Error releasing lock for operation {operation_name}: {e}"
            )
            return False

    def is_locked(self, operation_name):
        """
        Check if an operation is currently locked.
        Returns True if locked, False if available.
        """
        try:
            lock_info = self.get_item({"operation_name": operation_name})
            return lock_info is not None

        except Exception as e:
            logger.exception(
                f"Error checking lock status for operation {operation_name}: {e}"
            )
            return True  # Assume locked on error for safety

    def get_lock_info(self, operation_name):
        """
        Get detailed lock information for an operation.
        Returns lock details or None if not locked.
        """
        try:
            lock_info = self.get_item({"operation_name": operation_name})
            if lock_info:
                return {
                    "operation_name": lock_info.get("operation_name", {}).get("S"),
                    "lock_id": lock_info.get("lock_id", {}).get("S"),
                    "created_at": int(lock_info.get("created_at", {}).get("N", 0)),
                    "status": lock_info.get("status", {}).get("S"),
                    "lambda_request_id": lock_info.get("lambda_request_id", {}).get(
                        "S"
                    ),
                }
            return None

        except Exception as e:
            logger.exception(
                f"Error getting lock info for operation {operation_name}: {e}"
            )
            return None

    def force_release_lock(self, operation_name):
        """
        Force release a lock (emergency use only).
        Use with caution - should only be used for manual cleanup.
        """
        try:
            success = self.delete_item({"operation_name": operation_name})
            if success:
                logger.warning(f"FORCE RELEASED lock for operation: {operation_name}")
            return success

        except Exception as e:
            logger.exception(
                f"Error force releasing lock for operation {operation_name}: {e}"
            )
            return False
