import json
from utilities.logging import get_logger
from utilities.aws import send_lambda_response
from utilities.sql import get_sql_connection, execute_sql_query
from user import User

logger = get_logger(name="save_modified_resume")


@send_lambda_response(logger)
def lambda_handler(event, context):
    email = event["requestContext"]["authorizer"].get("email")
    if not email:
        logger.exception(
            f"User email not found in authorizer lambda response - \n{event}"
        )
        raise

    user = User(email=email)

    try:
        body = json.loads(event.get("body", "{}"))
        resume_data = body.get("resumeData")

        if not resume_data:
            logger.error("Resume data not found in request body")
            raise ValueError("Resume data is required")

        con = get_sql_connection()
        try:
            update_query = f"""
                UPDATE users.users 
                SET modified_resume = '{json.dumps(resume_data)}'
                WHERE id = {user.id}
            """
            execute_sql_query(update_query, con=con)

            return
        finally:
            con.close()

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise
    except Exception as e:
        logger.exception(f"Error saving modified resume: {str(e)}")
        raise
