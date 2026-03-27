import os
from typing import Optional
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from structlog import get_logger

from exceptions.custom_exceptions import AIProcessingException

logger = get_logger(__name__)

OPENAI_ERRORS = {
    RateLimitError: ("warning", "rate limited. Please try again shortly."),
    APITimeoutError: ("warning", "request timed out."),
    APIConnectionError: ("error", "connection failed."),
    APIError: ("error", "service error."),
}


class OpenAIChatAdapter:
    """Adapter for OpenAI API interactions via LangChain.

    Translates between LangChain message format and the domain layer.
    Catches all OpenAI errors at source and converts to AIProcessingException.
    """

    def __init__(self, model: Optional[str] = None, temperature: float = 0.0) -> None:

        env_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        base_url = os.getenv("OPENAI_BASE_URL")

        self._llm = ChatOpenAI(
            model=model or env_model,
            temperature=temperature,
            timeout=120,
            base_url=base_url,
        )
        logger.info("Initializing LLM adapter", model=self._llm.model_name, base_url=base_url)

    async def chat_with_tools(
        self,
        messages: list[BaseMessage],
        tools: list[dict],
        tool_choice: str = "auto",
    ) -> tuple[str, list, AIMessage]:
        """Call LLM with tools. Returns (content, tool_calls, raw_message)."""
        try:
            llm_with_tools = self._llm.bind_tools(tools, tool_choice=tool_choice)
            response = await llm_with_tools.ainvoke(messages)
            return _extract_content(response), response.tool_calls or [], response
        except Exception as e:
            raise self._handle_error(e) from e

    async def chat(self, messages: list[BaseMessage]) -> tuple[str, AIMessage]:
        """Simple chat without tools. Returns (content, raw_message)."""
        try:
            response = await self._llm.ainvoke(messages)
            return _extract_content(response), response
        except Exception as e:
            raise self._handle_error(e) from e

    def _handle_error(self, e: Exception) -> AIProcessingException:
        """Convert OpenAI error to AIProcessingException."""
        log_level, message = OPENAI_ERRORS.get(type(e), ("error", "unexpected error."))
        getattr(logger, log_level)(
            "OpenAI error", model=self._llm.model_name, error=str(e)
        )
        return AIProcessingException(
            f"OpenAI ({self._llm.model_name}) {message}",
            details={
                "provider": "openai",
                "model": self._llm.model_name,
                "error": str(e),
            },
        )


def _extract_content(response: AIMessage) -> str:
    """Extract string content from AIMessage, handling various formats."""
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content or "")
