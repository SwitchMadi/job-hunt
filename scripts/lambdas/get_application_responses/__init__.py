import json
from datetime import datetime
from user import User
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output
from utilities.aws import send_lambda_response

logger = get_logger(name="get_application_responses")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Lambda function to get questions and responses for a specific job application.
    Uses job_hash_id to find the latest submitted application for that job.
    """
    try:
        # Extract user email from JWT token
        email = event["requestContext"]["authorizer"].get("email")
        if not email:
            logger.exception(
                f"User email not found in authorizer lambda response - \n{event}"
            )
            return {
                "statusCode": 401,
                "body": json.dumps({"message": "User email not found", "error": True}),
            }

        # Get job_hash_id from path parameters
        job_hash_id = event.get("pathParameters", {}).get("job_hash_id")
        if not job_hash_id:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {"message": "job_hash_id is required", "error": True}
                ),
            }

        # Get user object
        user = User(email=email)

        # First, get the job details and latest submitted application
        job_and_application_query = f"""
            SELECT 
                j.id as job_id,
                j.job_hash_id,
                j.title as job_title,
                j.company,
                j.location,
                j.employment_type,
                j.location_requirement,
                j.experience_requirement_min_years,
                j.experience_requirement_max_years,
                j.salary,
                j.technical_skills,
                j.job_url,
                j.job_posted_at,
                ja.id as application_id,
                ja.created_at as application_date
            FROM jobs.jobs j
            JOIN users.job_applications ja ON j.id = ja.job_id
            WHERE j.job_hash_id = '{job_hash_id}'
            AND ja.user_id = {user.id}
            AND ja.application_status = 'submitted'
            ORDER BY ja.created_at DESC
            LIMIT 1
        """

        job_and_app = get_sql_query_output(job_and_application_query)

        if not job_and_app:
            return {
                "statusCode": 404,
                "body": json.dumps(
                    {
                        "message": "Job application not found or you don't have access to it",
                        "error": True,
                    }
                ),
            }

        job_data = job_and_app[0]
        application_id = job_data["application_id"]

        # Get the latest response for each unique question for this application
        # First get the latest response per question, then order by id ASC
        responses_query = f"""
            WITH latest_responses AS (
                SELECT DISTINCT ON (question)
                    question,
                    response,
                    id
                FROM users.job_application_responses
                WHERE application_id = {application_id}
                ORDER BY question, id DESC
            )
            SELECT 
                question,
                response
            FROM latest_responses
            ORDER BY id ASC
        """

        responses = get_sql_query_output(responses_query)

        # Format the response
        formatted_responses = []
        for resp in responses:
            # Parse the response JSON and extract text content
            try:
                response_data = (
                    json.loads(resp["response"])
                    if isinstance(resp["response"], str)
                    else resp["response"]
                )

                # Extract text from response (handle different response formats)
                response_text = ""
                if isinstance(response_data, str):
                    response_text = response_data
                elif isinstance(response_data, dict):
                    # Look for common text fields
                    response_text = response_data.get(
                        "text", response_data.get("value", str(response_data))
                    )
                elif isinstance(response_data, list):
                    response_text = ", ".join(str(item) for item in response_data)
                else:
                    response_text = str(response_data)

                formatted_responses.append(
                    {"question": resp["question"], "response": response_text}
                )
            except (json.JSONDecodeError, TypeError) as e:
                # If parsing fails, use the raw response
                logger.warning(
                    f"Failed to parse response for application {application_id}: {e}"
                )
                formatted_responses.append(
                    {"question": resp["question"], "response": str(resp["response"])}
                )

        # Format application date
        app_date = datetime.fromtimestamp(job_data["application_date"]).strftime(
            "%b %d, %Y"
        )

        # Format job posted date
        job_posted_date = ""
        if job_data["job_posted_at"]:
            job_posted_date = datetime.fromtimestamp(
                job_data["job_posted_at"]
            ).strftime("%b %d, %Y")

        # Format experience requirement
        experience_text = ""
        if (
            job_data["experience_requirement_min_years"] is not None
            and job_data["experience_requirement_max_years"] is not None
        ):
            if (
                job_data["experience_requirement_min_years"]
                == job_data["experience_requirement_max_years"]
            ):
                experience_text = (
                    f"{job_data['experience_requirement_min_years']} years"
                )
            else:
                experience_text = f"{job_data['experience_requirement_min_years']}-{job_data['experience_requirement_max_years']} years"
        elif job_data["experience_requirement_min_years"] is not None:
            experience_text = f"{job_data['experience_requirement_min_years']}+ years"
        elif job_data["experience_requirement_max_years"] is not None:
            experience_text = (
                f"Up to {job_data['experience_requirement_max_years']} years"
            )

        response_data = {
            "job": {
                "job_hash_id": job_data["job_hash_id"],
                "job_title": job_data["job_title"],
                "company": job_data["company"],
                "location": job_data["location"],
                "employment_type": job_data["employment_type"],
                "location_requirement": job_data["location_requirement"],
                "experience_requirement": experience_text,
                "salary": job_data["salary"],
                "technical_skills": job_data["technical_skills"],
                "job_url": job_data["job_url"],
                "job_posted_date": job_posted_date,
                "application_date": app_date,
            },
            "responses": formatted_responses,
        }

        logger.info(
            f"Retrieved {len(formatted_responses)} responses for application {application_id} (job {job_hash_id}) for user {email}"
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"data": response_data, "success": True}),
        }

    except Exception as e:
        logger.exception(f"Error getting application responses: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to get application responses: {str(e)}",
                    "error": True,
                }
            ),
        }
