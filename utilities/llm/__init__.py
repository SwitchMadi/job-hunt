import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar, Type, Optional, Any, Union

import dotenv
import yaml
from pydantic import BaseModel

from utilities import get_call_trace
from utilities.logging import get_logger

dotenv.load_dotenv()

T = TypeVar("T", bound=BaseModel)


@dataclass
class TokenUsage:
    """Token usage tracking."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class CostUsage:
    """Cost tracking."""

    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0


@dataclass
class ModelCostUsage:
    """Cost tracking per provider + model + input/output."""

    provider: str
    model: str
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class EnumEncoder(json.JSONEncoder):
    """JSON encoder for Enum types."""

    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


# Static pricing mapping per 1M tokens
# Format: "provider:model" -> {"input": cost_per_1M, "output": cost_per_1M}
# Prices are in USD per 1 million tokens
# Update these prices periodically as providers change their pricing
_MODEL_PRICING = {
    # OpenAI models
    "openai:gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai:gpt-5-nano": {"input": 0.05, "output": 0.40},
    "openai:gpt-5-mini": {"input": 0.125, "output": 1.00},
    # Anthropic models
    "anthropic:claude-3-5-sonnet-latest": {"input": 3.00, "output": 15.00},
    "anthropic:claude-3-5-haiku-latest": {"input": 0.25, "output": 1.25},
    "anthropic:claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic:claude-3-opus": {"input": 15.00, "output": 75.00},
    # Google Gemini models
    "gemini:gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini:gemini-2.5-pro-preview-06-05": {"input": 1.25, "output": 5.00},
    "gemini:gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini:gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}


class LLMServiceInterface(ABC):
    """
    Abstract interface for LLM service implementations.
    Follows the same pattern as PaymentGatewayInterface.
    """

    @abstractmethod
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
        Signature matches get_gpt_response() exactly for drop-in replacement.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            response_format: Optional Pydantic model for structured output
            sleep_time: Ignored (kept for signature compatibility)
            timeout: Optional timeout in seconds
            images: Optional list of image URLs (default: empty list)
            model: Model alias or name (default/intermediate/complex or direct name)

        Returns:
            - If response_format is None: str (raw response)
            - If response_format is provided: tuple(bool, T) matching current signature
        """
        pass

    @abstractmethod
    def query_file(
        self,
        query: str,
        file: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """
        Query a file using file search (RAG with vector search).
        Signature matches query_file() exactly for drop-in replacement.

        Args:
            query: Query string
            file: Path to file to query
            system_prompt: Optional system prompt (defaults to resume parser prompt)
            model: Model alias or name

        Returns:
            Response text from file query
        """
        pass


class BaseLLMService:
    """
    Base class with shared functionality for LLM service implementations.
    Provides token tracking, cost calculation, model resolution, and logging.
    """

    # Class variables shared across all instances (stored in __dict__ to avoid property conflicts)
    _shared_cumulative_usage: TokenUsage = None
    _shared_cumulative_cost: CostUsage = None
    _shared_model_costs: dict[str, ModelCostUsage] = None

    def __init__(self, provider: str, config_path: str = "config.yml"):
        """
        Initialize base LLM service.

        Args:
            provider: Provider name (e.g., "openai")
            config_path: Path to config.yml file
        """
        self.provider = provider
        self.config = yaml.safe_load(open(config_path))
        self.logger = get_logger(name="llm")

        # Initialize shared class variables if not already initialized
        if BaseLLMService._shared_cumulative_usage is None:
            BaseLLMService._shared_cumulative_usage = TokenUsage()
        if BaseLLMService._shared_cumulative_cost is None:
            BaseLLMService._shared_cumulative_cost = CostUsage()
        if BaseLLMService._shared_model_costs is None:
            BaseLLMService._shared_model_costs = {}

        # Provider configuration
        self._provider_config = self.config.get("llm_providers", {})

    def _calculate_cost(
        self, model_str: str, input_tokens: int, output_tokens: int
    ) -> dict[str, float]:
        """
        Calculate cost using static pricing mapping.

        Args:
            model_str: Model string (e.g., "openai:gpt-4o-mini")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Dictionary with 'input_cost', 'output_cost', and 'total_cost'
        """
        # Get pricing for this model
        pricing = _MODEL_PRICING.get(model_str)

        if not pricing:
            # Try to find a fallback by provider
            provider = model_str.split(":")[0] if ":" in model_str else self.provider
            model_name = model_str.split(":")[1] if ":" in model_str else model_str

            # Try common fallbacks
            fallback_keys = [
                f"{provider}:{model_name}",
                f"{provider}:{model_name.split('-')[0]}",  # Try base model name
            ]

            for key in fallback_keys:
                if key in _MODEL_PRICING:
                    pricing = _MODEL_PRICING[key]
                    self.logger.warn(
                        f"Using fallback pricing for {model_str} -> {key}. "
                        f"Consider adding exact pricing for {model_str}."
                    )
                    break

            if not pricing:
                self.logger.warn(
                    f"No pricing information found for {model_str}. "
                    f"Cost tracking will be skipped for this model."
                )
                return {"input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0}

        # Calculate costs (pricing is per 1M tokens)
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_cost = input_cost + output_cost

        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
        }

    def _resolve_model(self, model: Optional[str] = None) -> str:
        """
        Resolve model alias to actual model name.

        Args:
            model: Model alias ("default", "intermediate", "complex") or direct model name

        Returns:
            Model name string (e.g., "gpt-4o-mini")
        """
        if model is None:
            model = "default"

        # Map aliases to actual model names for this provider
        if model in ("default", "intermediate", "complex"):
            provider_config = self._provider_config.get(self.provider, {})
            model_name = provider_config.get("models", {}).get(model)

            if not model_name:
                raise ValueError(
                    f"Model alias '{model}' not found for provider '{self.provider}'"
                )
        else:
            # Direct model name - remove provider prefix if present
            if ":" in model:
                provided_provider = model.split(":")[0]
                if provided_provider != self.provider:
                    self.logger.warn(
                        f"Model '{model}' specifies provider '{provided_provider}', "
                        f"but instance is configured for '{self.provider}'. Using '{provided_provider}' model."
                    )
                model_name = model.split(":")[1]
            else:
                model_name = model

        return model_name

    def _log_call_trace(self):
        """Log the call trace of the function that called this function."""
        stack = get_call_trace()
        trace = []
        for frame in stack[:-3]:  # Exclude last 3 frames from this module
            module = frame["module"]
            func_name = frame["function"]
            trace.append(f"{module}.{func_name}")
        self.logger.info(f"LLM call trace: {' -> '.join(trace)}")

    def _update_token_usage(self, usage: TokenUsage, model_name: str):
        """
        Update cumulative token usage and cost from standardized TokenUsage.
        Automatically logs comprehensive usage and cost information.

        Each implementation must convert provider-specific usage format to TokenUsage
        before calling this method.

        Args:
            usage: TokenUsage object with standardized token counts
            model_name: Model name (e.g., "gpt-4o-mini") for cost calculation
        """
        if usage is None:
            self.logger.warning("Token usage is None, skipping tracking")
            return

        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        total_tokens = usage.total_tokens

        if total_tokens == 0:
            self.logger.debug("Token usage is zero, skipping tracking")
            return

        # Update cumulative token usage (shared across all instances)
        BaseLLMService._shared_cumulative_usage.prompt_tokens += prompt_tokens
        BaseLLMService._shared_cumulative_usage.completion_tokens += completion_tokens
        BaseLLMService._shared_cumulative_usage.total_tokens += total_tokens

        # Create model key for granular tracking
        model_key = f"{self.provider}:{model_name}"

        # Calculate cost using static pricing mapping
        cost_info = self._calculate_cost(model_key, prompt_tokens, completion_tokens)
        input_cost = cost_info["input_cost"]
        output_cost = cost_info["output_cost"]
        total_cost = cost_info["total_cost"]

        # Update cumulative cost (shared across all instances)
        BaseLLMService._shared_cumulative_cost.input_cost += input_cost
        BaseLLMService._shared_cumulative_cost.output_cost += output_cost
        BaseLLMService._shared_cumulative_cost.total_cost += total_cost

        # Update granular cost tracking per provider + model + input/output (shared across all instances)
        if model_key not in BaseLLMService._shared_model_costs:
            BaseLLMService._shared_model_costs[model_key] = ModelCostUsage(
                provider=self.provider, model=model_name
            )

        model_cost = BaseLLMService._shared_model_costs[model_key]
        model_cost.input_cost += input_cost
        model_cost.output_cost += output_cost
        model_cost.total_cost += total_cost
        model_cost.input_tokens += prompt_tokens
        model_cost.output_tokens += completion_tokens
        model_cost.total_tokens += total_tokens

        # Automatic comprehensive logging after each LLM call
        # Format: Consistent structure with clear sections

        # Section 1: Current call details
        self.logger.info(
            f"[Call] {self.provider}:{model_name} | "
            f"Tokens: {total_tokens} (Input: {prompt_tokens}, Output: {completion_tokens})"
        )

        if total_cost > 0:
            if input_cost > 0 or output_cost > 0:
                self.logger.info(
                    f"[Call] {self.provider}:{model_name} | "
                    f"Cost: ${total_cost:.6f} (Input: ${input_cost:.6f}, Output: ${output_cost:.6f})"
                )
            else:
                self.logger.info(
                    f"[Call] {self.provider}:{model_name} | "
                    f"Cost: ${total_cost:.6f} (input/output split unavailable)"
                )

        # Section 2: Cumulative totals across all providers/models
        self.logger.info(
            f"[Cumulative] All Providers/Models | "
            f"Tokens: {BaseLLMService._shared_cumulative_usage.total_tokens} "
            f"(Input: {BaseLLMService._shared_cumulative_usage.prompt_tokens}, "
            f"Output: {BaseLLMService._shared_cumulative_usage.completion_tokens})"
        )

        if BaseLLMService._shared_cumulative_cost.total_cost > 0:
            self.logger.info(
                f"[Cumulative] All Providers/Models | "
                f"Cost: ${BaseLLMService._shared_cumulative_cost.total_cost:.6f} "
                f"(Input: ${BaseLLMService._shared_cumulative_cost.input_cost:.6f}, "
                f"Output: ${BaseLLMService._shared_cumulative_cost.output_cost:.6f})"
            )

        # Section 3: Per-model cumulative totals (log ALL models in the dict)
        if BaseLLMService._shared_model_costs:
            self.logger.info(
                f"[Models] Per-model cumulative totals ({len(BaseLLMService._shared_model_costs)} model(s)):"
            )
            for model_key, model_cost_data in sorted(
                BaseLLMService._shared_model_costs.items()
            ):
                if model_cost_data.total_tokens > 0:
                    self.logger.info(
                        f"  • {model_key} | "
                        f"Tokens: {model_cost_data.total_tokens} "
                        f"(Input: {model_cost_data.input_tokens}, Output: {model_cost_data.output_tokens}) | "
                        f"Cost: ${model_cost_data.total_cost:.6f} "
                        f"(Input: ${model_cost_data.input_cost:.6f}, Output: ${model_cost_data.output_cost:.6f})"
                    )


# Module-level dictionary of singleton instances per provider
_provider_instances: dict[str, LLMServiceInterface] = {}


def create_llm_service(
    provider: Optional[str] = None, config_path: str = "config.yml"
) -> LLMServiceInterface:
    """
    Factory function to create LLM service instances.
    Implements singleton pattern per provider - returns the same instance for each provider.

    Args:
        provider: Provider name ("openai", "anthropic", etc.)
                 If None, uses default from config
        config_path: Path to config.yml file

    Returns:
        LLMServiceInterface instance (singleton per provider)
    """
    config = yaml.safe_load(open(config_path))
    provider_config = config.get("llm_providers", {})

    # Determine provider
    if provider is None:
        provider = provider_config.get("default", "openai")

    # Return existing singleton for this provider if it exists
    if provider in _provider_instances:
        return _provider_instances[provider]

    # Validate provider exists in config
    if provider_config and provider not in provider_config:
        raise ValueError(
            f"Provider '{provider}' not found in config. "
            f"Available: {list(provider_config.keys())}"
        )

    # Create appropriate implementation
    if provider == "openai":
        from utilities.llm.openai_service import OpenAILLMService

        instance = OpenAILLMService(config_path=config_path)
    elif provider == "anthropic":
        raise NotImplementedError("Anthropic provider not yet implemented")
    elif provider == "gemini":
        raise NotImplementedError("Gemini provider not yet implemented")
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    # Store singleton instance for this provider
    _provider_instances[provider] = instance
    return instance


# Export main classes and functions
__all__ = [
    "LLMServiceInterface",
    "BaseLLMService",
    "TokenUsage",
    "CostUsage",
    "ModelCostUsage",
    "EnumEncoder",
    "create_llm_service",
]
