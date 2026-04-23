import boto3
import os
import dotenv
import json
import functools

dotenv.load_dotenv()


def get_aws_client(service_name, endpoint_url=None):
    config = {
        "service_name": service_name,
        "aws_access_key_id": os.getenv("JH_AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("JH_AWS_SECRET_ACCESS_KEY"),
        "region_name": "ap-south-1",
    }

    if endpoint_url:
        config["endpoint_url"] = endpoint_url

    client = boto3.client(**config)
    return client


def send_lambda_response(logger):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(event, context, *args, **kwargs):
            allowed_origin = os.getenv("ALLOWED_ORIGIN", "*")

            cors_headers = {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": allowed_origin,
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            }

            # ✅ Handle OPTIONS preflight automatically
            if event.get("httpMethod", "").upper() == "OPTIONS":
                return {
                    "statusCode": 200,
                    "headers": cors_headers,
                    "body": json.dumps({"message": "CORS preflight OK"}),
                }

            try:
                result = func(event, context, *args, **kwargs)

                # If result is already a valid API Gateway response
                if isinstance(result, dict) and "statusCode" in result:
                    result.setdefault("headers", {})
                    result["headers"].update(cors_headers)

                    # Add body if missing
                    if "body" not in result:
                        message = result.get("message", "")
                        result["body"] = json.dumps({"message": message})

                    return result

                return {
                    "statusCode": 200,
                    "headers": cors_headers,
                    "body": json.dumps(result),
                }

            except Exception as e:
                logger.exception(f"Unhandled exception in Lambda - {e}")
                return {
                    "statusCode": 500,
                    "headers": cors_headers,
                    "body": json.dumps({"error": "Internal server error"}),
                }

        return wrapper

    return decorator
