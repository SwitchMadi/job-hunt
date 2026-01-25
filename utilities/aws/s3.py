from utilities.aws import get_aws_client
from utilities.logging import get_logger

logger = get_logger(name="s3")


class S3Bucket:
    def __init__(self, bucket_name):
        self.client = get_aws_client("s3")
        self.bucket_name = bucket_name

    def fetch_data(self, file_s3_path, file_local_path):
        logger.info(f"Fetching {file_s3_path} from S3 bucket {self.bucket_name}...")
        try:
            self.client.download_file(self.bucket_name, file_s3_path, file_local_path)
            return True
        except Exception as e:
            logger.exception(f"Error fetching data from S3 for {file_s3_path}: {e}")
            return False

    def upload_data(self, file_s3_path, file_local_path):
        try:
            logger.info(
                f"Uploading {file_local_path} to S3 bucket {self.bucket_name} at {file_s3_path}..."
            )
            self.client.upload_file(file_local_path, self.bucket_name, file_s3_path)
            return True
        except Exception as e:
            logger.exception(f"Error uploading data to S3 for {file_local_path}: {e}")
            return False

    def generate_presigned_url(self, file_s3_path, expiration=3600):
        """
        Generate a presigned URL for an S3 object

        Args:
            file_s3_path (str): The S3 object key/path
            expiration (int): Time in seconds for the URL to remain valid (default: 1 hour)

        Returns:
            str: Presigned URL or None if error
        """
        try:
            logger.info(
                f"Generating presigned URL for {file_s3_path} in bucket {self.bucket_name}"
            )

            # Use boto3's generate_presigned_url method
            presigned_url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": file_s3_path},
                ExpiresIn=expiration,
            )

            logger.info(f"Successfully generated presigned URL for {file_s3_path}")
            return presigned_url

        except Exception as e:
            logger.exception(f"Error generating presigned URL for {file_s3_path}: {e}")
            return None

    def get_object_metadata(self, file_s3_path):
        """
        Get metadata for an S3 object including last modified timestamp

        Args:
            file_s3_path (str): The S3 object key/path

        Returns:
            dict: Object metadata or None if error
        """
        try:
            logger.info(
                f"Getting metadata for {file_s3_path} in bucket {self.bucket_name}"
            )

            response = self.client.head_object(
                Bucket=self.bucket_name, Key=file_s3_path
            )

            metadata = {
                "last_modified": response.get("LastModified"),
                "content_length": response.get("ContentLength"),
                "content_type": response.get("ContentType"),
                "etag": response.get("ETag"),
            }

            logger.info(f"Successfully retrieved metadata for {file_s3_path}")
            return metadata

        except Exception as e:
            logger.exception(f"Error getting metadata for {file_s3_path}: {e}")
            return None
