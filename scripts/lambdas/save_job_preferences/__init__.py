import json
import time

from utilities.logging import get_logger
from utilities.aws import send_lambda_response
from utilities.sql import get_sql_connection, get_sql_query_output, execute_sql_query
from user import User

logger = get_logger(name="save_job_preferences")


@send_lambda_response(logger)
def lambda_handler(event, context):
    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    user = User(email=email)
    preferences = json.loads(event.get("body", "{}"))

    con = get_sql_connection()
    try:
        # Resolve or create job_filter_id
        job_filter_id = get_or_create_job_filter_id(user, con=con)

        disable_preferences_query = f"""
            update users.job_filter_preferences
            set is_active = false
            where job_filter_id = {job_filter_id};
        """
        execute_sql_query(disable_preferences_query, con=con)

        # Convert preferences into DB-ready rows
        insert_values = prepare_filter_preferences(user, preferences, job_filter_id)

        # Execute insert query
        insert_query = """
                    INSERT INTO users.job_filter_preferences (
                        user_id, job_field, value, is_active, created_at, updated_at, is_preferred, job_filter_id
                    ) VALUES %s
                """
        execute_sql_query((insert_query, insert_values), con=con)

        return
    finally:
        con.close()


def get_or_create_job_filter_id(user, filter_name="Job preferences", con=None):
    query = f"SELECT id FROM users.job_filters WHERE user_id = {user.id} AND name = '{filter_name}' AND is_active = true;"
    result = get_sql_query_output(query, con=con)
    if result:
        return result[0]["id"]

    # Fallback: create new filter
    ts = int(time.time())
    insert_query = f"""
        INSERT INTO users.job_filters (user_id, name, is_active, created_at, updated_at)
        VALUES ({user.id}, '{filter_name}', true, {ts}, {ts})
        RETURNING id
        """
    result = get_sql_query_output(insert_query, con=con)
    return result[0]["id"]


def prepare_filter_preferences(user, preferences, job_filter_id):
    created_at = updated_at = int(time.time())
    values = []

    def add(field, value):
        values.append(
            (
                user.id,
                field,
                value,
                True,  # is_active
                created_at,
                updated_at,
                True,  # is_preferred
                job_filter_id,
            )
        )

    for domain in preferences.get("domains", []):
        add("job_domain", domain)

    for mode in preferences.get("locationRequirement", []):
        add("location_requirement", mode)

    for loc in preferences.get("locations", []):
        add("location", loc)

    for skill in preferences.get("skills", []):
        add("technical_skills", skill)

    exp = preferences.get("experience", {})
    if isinstance(exp, dict):
        if exp.get("min") is not None:
            add("experience_requirement_min_years", str(exp["min"]))
        if exp.get("max") is not None:
            add("experience_requirement_max_years", str(exp["max"]))

    return values
