import os
import dotenv
from openai import OpenAI, RateLimitError
from httpx import HTTPStatusError
import time
import yaml

from utilities.logging import get_logger

dotenv.load_dotenv()
logger = get_logger(name="gpt")
client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
config = yaml.safe_load(open("config.yml"))


def get_gpt_response(system_prompt, user_prompt, response_format=None, sleep_time=1):
    try:
        payload = {
            "model": config["openai_model"],
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        }

        if response_format is not None:
            payload["response_format"] = response_format

            completion = client.beta.chat.completions.parse(**payload)
            resp = completion.choices[0].message

            if resp.refusal:
                logger.warn(
                    f"GPT could not respond with structured output - \n{resp.refusal}"
                )
                return False, resp.refusal
            else:
                logger.debug(f"GPT responded with structured output - \n{resp.parsed}")
                return True, resp.parsed
        else:
            completion = client.chat.completions.create(**payload)
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
