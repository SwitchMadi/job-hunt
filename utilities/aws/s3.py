from utilities.aws import get_aws_client
from utilities.logging import get_logger


logger = get_logger(name="s3", file_name="job-hunt")


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
            self.client.upload_file(file_local_path, self.bucket_name, file_s3_path)
            return True
        except Exception as e:
            logger.exception(f"Error uploading data to S3 for {file_local_path}: {e}")
            return False
