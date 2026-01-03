import json
import os
import time
from typing import TypeVar, Type, Optional, Union

import dotenv
from openai import OpenAI, RateLimitError
from httpx import HTTPStatusError
from pydantic import BaseModel

from utilities.llm import (
    LLMServiceInterface,
    BaseLLMService,
    EnumEncoder,
    TokenUsage,
)
from utilities.logging import get_logger

dotenv.load_dotenv()

T = TypeVar("T", bound=BaseModel)


class OpenAILLMService(LLMServiceInterface, BaseLLMService):
    """
    OpenAI implementation of LLMServiceInterface.
    Follows the same pattern as the existing GPT utility (get_gpt_response, query_file).
    """

    def __init__(self, config_path: str = "config.yml"):
        """
        Initialize OpenAI LLM service.

        Args:
            config_path: Path to config.yml file
        """
        BaseLLMService.__init__(self, provider="openai", config_path=config_path)

        # Initialize OpenAI client (using OPENAI_KEY like existing GPT utility)
        api_key = os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_KEY or OPENAI_API_KEY environment variable not set"
            )

        self.client = OpenAI(api_key=api_key)
        self.logger.info("OpenAILLMService initialized")

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[Type[T]] = None,
        sleep_time: int = 1,
        timeout: Optional[float] = None,
        images: Optional[list[str]] = None,
        model: Optional[str] = None,
    ) -> Union[str, tuple[bool, T]]:
        """
        Chat completion with optional structured output.
        Implements LLMServiceInterface.chat() for OpenAI provider.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            response_format: Optional Pydantic model for structured output
            sleep_time: Used for retry backoff (kept for signature compatibility)
            timeout: Optional timeout in seconds
            images: Optional list of image URLs (default: empty list)
            model: Model alias or name (default/intermediate/complex or direct name)

        Returns:
            - If response_format is None: str (raw response)
            - If response_format is provided: tuple(bool, T) matching current signature
        """
        self._log_call_trace()

        if images is None:
            images = []

        try:
            # Build user content (following get_gpt_response pattern)
            user_content = [{"type": "text", "text": user_prompt}]

            for image in images:
                user_content.append({"type": "image_url", "image_url": {"url": image}})

            # Resolve model name
            model_name = self._resolve_model(model)

            # Build payload (following get_gpt_response pattern)
            payload = {
                "model": model_name,
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

            if timeout is not None:
                payload["timeout"] = timeout

            # Handle structured output (following get_gpt_response pattern)
            if response_format is not None:
                payload["response_format"] = response_format

                # Use beta.chat.completions.parse() for structured output
                completion = self.client.beta.chat.completions.parse(**payload)
                resp = completion.choices[0].message

                # Update token usage and cost (automatic logging happens in _update_token_usage)
                if hasattr(completion, "usage") and completion.usage:
                    usage = TokenUsage(
                        prompt_tokens=completion.usage.prompt_tokens,
                        completion_tokens=completion.usage.completion_tokens,
                        total_tokens=completion.usage.total_tokens,
                    )
                    self._update_token_usage(usage, model_name)
                else:
                    self.logger.warning(
                        f"[{self.provider}:{model_name}] No usage data available for structured output call"
                    )

                # Check for refusal (following get_gpt_response pattern)
                if resp.refusal:
                    self.logger.warn(
                        f"GPT could not respond with structured output - \n{resp.refusal}"
                    )
                    return False, resp.refusal
                else:
                    self.logger.info(
                        f"GPT responded with structured output - \n%s",
                        json.dumps(resp.parsed.dict(), indent=2, cls=EnumEncoder),
                    )
                    return True, resp.parsed
            else:
                # Regular text completion (following get_gpt_response pattern)
                completion = self.client.chat.completions.create(**payload)
                resp = completion.choices[0].message.content

                # Update token usage and cost (automatic logging happens in _update_token_usage)
                if hasattr(completion, "usage") and completion.usage:
                    usage = TokenUsage(
                        prompt_tokens=completion.usage.prompt_tokens,
                        completion_tokens=completion.usage.completion_tokens,
                        total_tokens=completion.usage.total_tokens,
                    )
                    self._update_token_usage(usage, model_name)
                else:
                    self.logger.warning(
                        f"[{self.provider}:{model_name}] No usage data available for text completion call"
                    )

                self.logger.debug(f"GPT response - \n{resp}")
                return resp

        except (RateLimitError, HTTPStatusError) as e:
            # Handle rate limits and HTTP errors gracefully
            error_message = str(e)

            # Check status code (RateLimitError has status_code, HTTPStatusError has response.status_code)
            status_code = None
            if isinstance(e, RateLimitError):
                status_code = getattr(e, "status_code", None)
            elif hasattr(e, "response"):
                status_code = e.response.status_code if e.response else None

            if status_code == 429:
                # Check for quota exceeded (non-retryable)
                if (
                    "You exceeded your current quota" in error_message
                    or "insufficient_quota" in error_message
                    or sleep_time >= 60
                ):
                    self.logger.error(
                        f"OpenAI API quota exceeded or max retries reached: {error_message}"
                    )
                    if response_format:
                        return False, f"API quota exceeded: {error_message}"
                    return None

                # Rate limit exceeded but retryable
                self.logger.warning(
                    f"OpenAI API rate limit exceeded, retrying in {sleep_time} seconds..."
                )
                time.sleep(sleep_time)
                return self.chat(
                    system_prompt,
                    user_prompt,
                    response_format=response_format,
                    sleep_time=2 * sleep_time,
                    timeout=timeout,
                    images=images,
                    model=model,
                )
            else:
                # Other HTTP errors
                self.logger.error(
                    f"HTTP error occurred while calling OpenAI API (status {status_code}): {error_message}"
                )
                if response_format:
                    return False, f"HTTP error: {error_message}"
                return None
        except Exception as e:
            # Unexpected errors
            error_message = str(e)
            self.logger.exception(
                f"An unexpected error occurred while calling OpenAI API: {error_message}"
            )
            if response_format:
                return False, f"Unexpected error: {error_message}"
            return None

    def query_file(
        self,
        query: str,
        file: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        Query a file using OpenAI Assistants API.
        Implements LLMServiceInterface.query_file() for OpenAI provider.

        Args:
            query: Query string
            file: Path to file to query
            system_prompt: Optional system prompt (defaults to resume parser prompt)
            model: Model alias or name

        Returns:
            Response text from file query
        """
        self._log_call_trace()

        if system_prompt is None:
            system_prompt = (
                "You are a resume parser assistant. "
                "Use your knowledge base to extract information from the resume."
            )

        try:
            # Resolve model name
            model_name = self._resolve_model(model)

            # Create file assistant (following query_file pattern)
            assistant = self.client.beta.assistants.create(
                name="Resume parser assistant",
                instructions=system_prompt,
                model=model_name,
                tools=[{"type": "file_search"}],
            )

            # Create vector store and upload file (following query_file pattern)
            vector_store = self.client.beta.vector_stores.create(name="Resume")

            # Use upload_and_poll helper (following query_file pattern)
            with open(file, "rb") as f:
                file_batch = (
                    self.client.beta.vector_stores.file_batches.upload_and_poll(
                        vector_store_id=vector_store.id, files=[f]
                    )
                )

            self.logger.info(f"file_batch status - {file_batch.status}")
            self.logger.info(f"file_batch files count - {file_batch.file_counts}")

            # Update assistant with vector store (following query_file pattern)
            assistant = self.client.beta.assistants.update(
                assistant_id=assistant.id,
                tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
            )

            # Create thread with message (following query_file pattern)
            thread = self.client.beta.threads.create(
                messages=[
                    {
                        "role": "user",
                        "content": query,
                    }
                ]
            )

            # Create and poll run (following query_file pattern)
            run = self.client.beta.threads.runs.create_and_poll(
                thread_id=thread.id, assistant_id=assistant.id
            )

            # Get messages (following query_file pattern)
            messages = list(
                self.client.beta.threads.messages.list(
                    thread_id=thread.id, run_id=run.id
                )
            )

            # Check if messages exist and have content
            if not messages:
                error_msg = "No messages returned from file query"
                self.logger.error(error_msg)
                raise ValueError(error_msg)

            if not messages[0].content:
                error_msg = "Message has no content"
                self.logger.error(error_msg)
                raise ValueError(error_msg)

            message_content = messages[0].content[0].text

            # Safely handle annotations
            annotations = getattr(message_content, "annotations", [])
            citations = []

            # Process citations (following query_file pattern)
            for index, annotation in enumerate(annotations):
                annotation_text = getattr(annotation, "text", "")
                if annotation_text:
                    message_content.value = message_content.value.replace(
                        annotation_text, f"[{index}]"
                    )
                if file_citation := getattr(annotation, "file_citation", None):
                    try:
                        cited_file = self.client.files.retrieve(file_citation.file_id)
                        citations.append(f"[{index}] {cited_file.filename}")
                    except Exception as cite_error:
                        self.logger.warning(
                            f"Failed to retrieve citation file: {cite_error}"
                        )

            # Update token usage if available (automatic logging happens in _update_token_usage)
            if hasattr(run, "usage") and run.usage:
                usage = TokenUsage(
                    prompt_tokens=run.usage.prompt_tokens,
                    completion_tokens=run.usage.completion_tokens,
                    total_tokens=run.usage.total_tokens,
                )
                self._update_token_usage(usage, model_name)
            else:
                self.logger.warning(
                    f"[{self.provider}:{model_name}] No usage data available for file query call"
                )

            response_text = getattr(message_content, "value", str(message_content))
            self.logger.info(f"File query response - \n{response_text}")
            return response_text

        except (RateLimitError, HTTPStatusError) as e:
            # Handle API errors gracefully
            error_message = str(e)

            # Check status code
            status_code = None
            if isinstance(e, RateLimitError):
                status_code = getattr(e, "status_code", None)
            elif hasattr(e, "response"):
                status_code = e.response.status_code if e.response else None

            if status_code == 429:
                if (
                    "You exceeded your current quota" in error_message
                    or "insufficient_quota" in error_message
                ):
                    self.logger.error(
                        f"OpenAI API quota exceeded while querying file: {error_message}"
                    )
                else:
                    self.logger.warning(
                        f"OpenAI API rate limit exceeded while querying file: {error_message}"
                    )
            else:
                self.logger.error(
                    f"HTTP error occurred while querying file (status {status_code}): {error_message}"
                )
            raise ValueError(f"Failed to query file: {error_message}") from e
        except Exception as e:
            # Handle all other errors gracefully
            error_message = str(e)
            self.logger.exception(f"Error querying file: {error_message}")
            raise ValueError(f"Failed to query file: {error_message}") from e
