import boto3
import os
import dotenv


dotenv.load_dotenv()


def get_aws_client(service_name):
    client = boto3.client(
        service_name,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name="ap-south-1",
    )
    return client
