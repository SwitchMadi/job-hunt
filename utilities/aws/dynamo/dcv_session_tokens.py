import time
from typing import Any, Dict, Optional

from . import BaseDynamoTable
from utilities.logging import get_logger

logger = get_logger(name="dcv_session_tokens")


class DcvSessionTokensTable(BaseDynamoTable):
    """Stores DCV browser-session tokens for Lambda validation when the URL is opened."""

    def __init__(self, table_name: str):
        if not (table_name or "").strip():
            raise ValueError("dcv_session_tokens_table name is required in config.yml (aws.dcv_session_tokens_table)")
        super().__init__(table_name.strip())

    def put_token(
        self,
        token: str,
        token_signature: str,
        *,
        job_id: Optional[str] = None,
        user_id: Optional[str] = None,
        job_application_id: Optional[str] = None,
        captcha_task_id: Optional[str] = None,
        ttl_epoch_seconds: Optional[int] = None,
    ) -> bool:
        try:
            now_ms = int(time.time() * 1000)
            item: Dict[str, Any] = {
                "token": token,
                "tokenSignature": token_signature,
                "createdAt": now_ms,
            }
            if job_id is not None:
                item["jobId"] = job_id
            if user_id is not None:
                item["userId"] = user_id
            if job_application_id is not None:
                item["jobApplicationId"] = job_application_id
            if captcha_task_id is not None:
                item["captchaTaskId"] = captcha_task_id
            if ttl_epoch_seconds is not None:
                item["ttl"] = ttl_epoch_seconds

            formatted_item = {}
            for key, value in item.items():
                if isinstance(value, str):
                    formatted_item[key] = {"S": value}
                elif isinstance(value, bool):
                    formatted_item[key] = {"BOOL": value}
                elif isinstance(value, int):
                    formatted_item[key] = {"N": str(value)}
                else:
                    formatted_item[key] = {"S": str(value)}

            self.client.put_item(TableName=self.table_name, Item=formatted_item)
            return True
        except Exception as e:
            logger.exception("Error storing DCV session token: %s", e)
            return False
