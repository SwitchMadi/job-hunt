import boto3
import os
import dotenv
import json
import functools


dotenv.load_dotenv()


def get_aws_client(service_name):
    client = boto3.client(
        service_name,
        aws_access_key_id=os.getenv("JH_AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("JH_AWS_SECRET_ACCESS_KEY"),
        region_name="ap-south-1",
    )
    return client


def send_lambda_response(logger):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)

                # If result is a valid API Gateway response, return as is
                if isinstance(result, dict) and "statusCode" in result:
                    return result

                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(result),
                }
            except Exception as e:
                logger.exception(f"Unhandled exception in Lambda - {e}")
                return {
                    "statusCode": 500,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"error": "Internal server error"}),
                }

        return wrapper

    return decorator
