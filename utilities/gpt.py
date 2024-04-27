import os
import dotenv
from openai import OpenAI

from utilities.logging import get_logger

dotenv.load_dotenv()
logger = get_logger(name="gpt", file_name="job-hunt")
client = OpenAI(api_key=os.getenv("OPENAI_KEY"))


def get_gpt_response(system_prompt, user_prompt):
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
