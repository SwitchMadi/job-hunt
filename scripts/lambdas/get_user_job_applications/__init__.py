import json
from datetime import datetime
from user import User
from utilities.logging import get_logger
from utilities.sql import get_sql_query_output
from utilities.aws import send_lambda_response

logger = get_logger(name="get_user_job_applications")


@send_lambda_response(logger)
def lambda_handler(event, context):
    """
    Lambda function to get user's job applications with pagination.
    Returns only submitted applications.
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

        # Get query parameters
        query_params = event.get("queryStringParameters") or {}
        page = int(query_params.get("page", 1))
        page_size = int(query_params.get("page_size", 10))

        # Validate pagination parameters
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 50:  # Max 50 per page
            page_size = 10

        offset = (page - 1) * page_size

        # Get user object
        user = User(email=email)

        # Get total count of submitted applications
        count_query = f"""
            SELECT COUNT(*) as total_count
            FROM users.job_applications ja
            JOIN jobs.jobs j ON ja.job_id = j.id
            WHERE ja.user_id = {user.id}
            AND ja.application_status = 'submitted'
        """
        count_result = get_sql_query_output(count_query)
        total_count = count_result[0]["total_count"] if count_result else 0

        # Get paginated job applications
        applications_query = f"""
            SELECT 
                ja.id as application_id,
                ja.created_at as application_date,
                ja.application_status,
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
                j.job_posted_at
            FROM users.job_applications ja
            JOIN jobs.jobs j ON ja.job_id = j.id
            WHERE ja.user_id = {user.id}
            AND ja.application_status = 'submitted'
            ORDER BY ja.created_at DESC
            LIMIT {page_size} OFFSET {offset}
        """

        applications = get_sql_query_output(applications_query)

        # Format the response
        formatted_applications = []
        for app in applications:
            # Format experience requirement
            experience_text = ""
            if (
                app["experience_requirement_min_years"] is not None
                and app["experience_requirement_max_years"] is not None
            ):
                if (
                    app["experience_requirement_min_years"]
                    == app["experience_requirement_max_years"]
                ):
                    experience_text = f"{app['experience_requirement_min_years']} years"
                else:
                    experience_text = f"{app['experience_requirement_min_years']}-{app['experience_requirement_max_years']} years"
            elif app["experience_requirement_min_years"] is not None:
                experience_text = f"{app['experience_requirement_min_years']}+ years"
            elif app["experience_requirement_max_years"] is not None:
                experience_text = (
                    f"Up to {app['experience_requirement_max_years']} years"
                )

            # Format application date
            app_date = datetime.fromtimestamp(app["application_date"]).strftime(
                "%b %d, %Y"
            )

            # Format job posted date
            job_posted_date = ""
            if app["job_posted_at"]:
                job_posted_date = datetime.fromtimestamp(app["job_posted_at"]).strftime(
                    "%b %d, %Y"
                )

            formatted_app = {
                "application_id": app["application_id"],
                "job_hash_id": app["job_hash_id"],
                "job_title": app["job_title"],
                "company": app["company"],
                "location": app["location"],
                "application_date": app_date,
                "job_posted_date": job_posted_date,
                "application_status": app["application_status"],
                "employment_type": app["employment_type"],
                "location_requirement": app["location_requirement"],
                "experience_requirement": experience_text,
                "salary": app["salary"],
                "technical_skills": app["technical_skills"],
                "job_url": app["job_url"],
            }
            formatted_applications.append(formatted_app)

        # Calculate pagination info
        total_pages = (total_count + page_size - 1) // page_size
        has_next_page = page < total_pages
        has_prev_page = page > 1

        response_data = {
            "applications": formatted_applications,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next_page": has_next_page,
                "has_prev_page": has_prev_page,
            },
        }

        logger.info(
            f"Retrieved {len(formatted_applications)} applications for user {email} (page {page})"
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"data": response_data, "success": True}),
        }

    except Exception as e:
        logger.exception(f"Error getting user job applications: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "message": f"Failed to get job applications: {str(e)}",
                    "error": True,
                }
            ),
        }
