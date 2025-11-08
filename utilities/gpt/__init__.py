import json
import os
import dotenv
from openai import OpenAI, RateLimitError
from httpx import HTTPStatusError
import time
import yaml
from enum import Enum

from utilities import get_call_trace
from utilities.logging import get_logger

dotenv.load_dotenv()
logger = get_logger(name="gpt")
client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
config = yaml.safe_load(open("config.yml"))
# Global token usage tracking
_cumulative_prompt_tokens = 0
_cumulative_completion_tokens = 0
_cumulative_total_tokens = 0


def _log_call_trace():
    """Log the call trace of the function that called this function."""
    stack = get_call_trace()

    trace = []
    for frame in stack[
        :-3
    ]:  # Exclude the last 3 frames which are likely from this module
        module = frame["module"]
        func_name = frame["function"]
        trace.append(f"{module}.{func_name}")

    logger.info(f"GPT call trace: {' -> '.join(trace)}")


def _update_token_usage(prompt_tokens, completion_tokens, total_tokens):
    """Update cumulative token usage and log both individual and cumulative usage."""
    global _cumulative_prompt_tokens, _cumulative_completion_tokens, _cumulative_total_tokens

    _cumulative_prompt_tokens += prompt_tokens
    _cumulative_completion_tokens += completion_tokens
    _cumulative_total_tokens += total_tokens

    # Log individual usage
    logger.info(
        f"Current OpenAI token usage - "
        f"Input: {prompt_tokens}, "
        f"Output: {completion_tokens}, "
        f"Total: {total_tokens}"
    )

    # Log cumulative usage
    logger.info(
        f"Cumulative token usage since start - "
        f"Input: {_cumulative_prompt_tokens}, "
        f"Output: {_cumulative_completion_tokens}, "
        f"Total: {_cumulative_total_tokens}"
    )


class EnumEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


def get_gpt_response(
    system_prompt,
    user_prompt,
    response_format=None,
    sleep_time=1,
    images=[],
    model=None,
):
    _log_call_trace()

    try:
        user_content = [{"type": "text", "text": user_prompt}]

        for image in images:
            user_content.append({"type": "image_url", "image_url": {"url": image}})

        # Use specified model or default model
        if model is None:
            model = config["openai_models"]["default"]
        elif model == "complex":
            model = config["openai_models"]["complex"]
        # If model is already a string (model name), use it directly

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        }

        if response_format is not None:
            payload["response_format"] = response_format

            completion = client.beta.chat.completions.parse(**payload)
            resp = completion.choices[0].message

            # Log token usage
            _update_token_usage(
                completion.usage.prompt_tokens,
                completion.usage.completion_tokens,
                completion.usage.total_tokens,
            )

            if resp.refusal:
                logger.warn(
                    f"GPT could not respond with structured output - \n{resp.refusal}"
                )
                return False, resp.refusal
            else:
                logger.info(
                    f"GPT responded with structured output - \n%s",
                    json.dumps(resp.parsed.dict(), indent=2, cls=EnumEncoder),
                )
                return True, resp.parsed
        else:
            completion = client.chat.completions.create(**payload)
            resp = completion.choices[0].message.content

            # Log token usage
            _update_token_usage(
                completion.usage.prompt_tokens,
                completion.usage.completion_tokens,
                completion.usage.total_tokens,
            )

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
                system_prompt,
                user_prompt,
                response_format=response_format,
                sleep_time=2 * sleep_time,
                images=images,
                model=model,
            )
        else:
            logger.exception(f"HTTP error occurred while calling Openai api: {e}")
            return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred while calling Openai api: {e}")
        return None
