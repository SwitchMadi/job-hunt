from utilities.logging import get_logger
from utilities.aws import send_lambda_response
from utilities.sql import get_sql_connection, get_sql_query_output
from user import User

logger = get_logger(name="get_job_preferences")


@send_lambda_response(logger)
def lambda_handler(event, context):
    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    user = User(email=email)
    con = get_sql_connection()
    try:
        # Get job filter ID for default preferences
        filter_query = f"""
            SELECT id 
            FROM users.job_filters 
            WHERE user_id = {user.id} 
            AND name = 'Job preferences' 
            AND is_active = true;
        """
        result = get_sql_query_output(filter_query, con=con)
        if not result:
            return {
                "domains": [],
                "experience": {"min": 0, "max": 20},
                "locationRequirement": [],
                "locations": [],
                "skills": [],
            }

        job_filter_id = result[0]["id"]

        # Fetch active preferences
        preferences_query = f"""
            SELECT job_field, value
            FROM users.job_filter_preferences
            WHERE job_filter_id = {job_filter_id}
            AND is_active = true;
        """
        preferences = get_sql_query_output(preferences_query, con=con)

        # Transform DB rows into response format
        response = {
            "domains": [],
            "experience": {"min": 0, "max": 20},
            "locationRequirement": [],
            "locations": [],
            "skills": [],
        }

        for pref in preferences:
            if pref["job_field"] == "job_domain":
                response["domains"].append(pref["value"])
            elif pref["job_field"] == "location_requirement":
                response["locationRequirement"].append(pref["value"])
            elif pref["job_field"] == "location":
                response["locations"].append(pref["value"])
            elif pref["job_field"] == "technical_skills":
                response["skills"].append(pref["value"])
            elif pref["job_field"] == "experience_requirement_min_years":
                response["experience"]["min"] = int(pref["value"])
            elif pref["job_field"] == "experience_requirement_max_years":
                response["experience"]["max"] = int(pref["value"])

        return response
    finally:
        con.close()
