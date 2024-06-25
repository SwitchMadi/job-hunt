import os
import dotenv
from openai import OpenAI, RateLimitError
from httpx import HTTPStatusError
import time

from utilities.logging import get_logger

dotenv.load_dotenv()
logger = get_logger(name="gpt", file_name="job-hunt")
client = OpenAI(api_key=os.getenv("OPENAI_KEY"))


def get_gpt_response(system_prompt, user_prompt, sleep_time=1):
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        resp = completion.choices[0].message.content
        logger.debug(f"GPT response - \n{resp}")
        return resp
    except (RateLimitError, HTTPStatusError) as e:
        if e.response.status_code == 429:
            if "You exceeded your current quota" in str(e) or sleep_time >= 60:
                logger.exception(f"429 error occurred while calling Openai api: {e}")
                return None

            logger.debug(
                f"Openai API rate limit exceeded, retrying in {sleep_time} seconds..."
            )
            time.sleep(sleep_time)
            return get_gpt_response(
                system_prompt, user_prompt, sleep_time=2 * sleep_time
            )
        else:
            logger.exception(f"HTTP error occurred while calling Openai api: {e}")
            return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred while calling Openai api: {e}")
        return None
