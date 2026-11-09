"""Asynchronous Google Gemini client wrapper leveraging the official google-genai SDK."""

import inspect
import logging
from typing import Any, Callable
from google import genai
from google.genai import types

from core.config import Settings, get_settings
from core.errors import GeminiAPIError

logger = logging.getLogger(__name__)


class GeminiClient:
    """Production-grade asynchronous wrapper for Google Gemini models."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self._settings: Settings = get_settings()
        self.model: str = model or self._settings.gemini_model
        resolved_api_key = api_key or self._settings.gemini_api_key_value

        # Support dependency injection for tests
        self.client: genai.Client = client or genai.Client(api_key=resolved_api_key)

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        """Generate text completions using Gemini 3.8 Flash asynchronously."""
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
            )
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                return response.text or ""
            except Exception as exc:
                if ("503" in str(exc) or "UNAVAILABLE" in str(exc)) and self.model != "gemini-3.5-flash":
                    logger.warning("Model %s unavailable (503); retrying with gemini-3.5-flash", self.model)
                    fallback_response = await self.client.aio.models.generate_content(
                        model="gemini-3.5-flash",
                        contents=prompt,
                        config=config,
                    )
                    return fallback_response.text or ""
                raise
        except Exception as exc:
            logger.error("Gemini text generation failed: %s", exc, exc_info=True)
            raise GeminiAPIError(f"Gemini API text generation error: {exc}") from exc

    async def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        prompt: str = (
            "Analyze this image in detail. Perform high-precision OCR to transcribe all visible text, "
            "financial figures, line items, timestamps, merchant/sender names, and receipts. "
            "Return a clean, structured Markdown breakdown."
        ),
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> str:
        """Analyze an image or document attachment using Gemini multimodal vision/OCR."""
        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
            )
            contents = [image_part, prompt]

            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            return response.text or ""
        except Exception as exc:
            logger.error("Gemini multimodal image analysis failed: %s", exc, exc_info=True)
            raise GeminiAPIError(f"Gemini API image analysis error: {exc}") from exc

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[Callable[..., Any]],
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_iterations: int = 5,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Execute conversational completion with automated tool calling / function dispatch.

        Args:
            prompt: User message or instruction.
            tools: List of callable Python functions with type hints and docstrings.
            system_instruction: Optional system instruction prompt.
            temperature: Sampling temperature.
            max_iterations: Safety limit for recursive tool dispatch turns.

        Returns:
            Tuple of (final_text_response, executed_tool_calls_history).
        """
        tool_map = {fn.__name__: fn for fn in tools}
        execution_history: list[dict[str, Any]] = []

        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                tools=tools,
            )

            # Initialize multi-turn contents
            contents: list[Any] = [prompt]

            current_model = self.model
            for _ in range(max_iterations):
                try:
                    response = await self.client.aio.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=config,
                    )
                except Exception as err:
                    if ("503" in str(err) or "UNAVAILABLE" in str(err)) and current_model != "gemini-3.1-flash-lite":
                        logger.warning("Model %s unavailable (503); retrying tool loop with gemini-3.1-flash-lite", current_model)
                        current_model = "gemini-3.1-flash-lite"
                        response = await self.client.aio.models.generate_content(
                            model=current_model,
                            contents=contents,
                            config=config,
                        )
                    else:
                        raise

                # Check if the model requested function execution
                function_calls = getattr(response, "function_calls", None)
                if not function_calls:
                    # Model provided final natural language response
                    return response.text or "", execution_history

                # Add model's intermediate candidate response to contents history
                candidates = getattr(response, "candidates", [])
                if candidates and candidates[0].content:
                    contents.append(candidates[0].content)

                # Execute every requested tool
                for call in function_calls:
                    fn_name = call.name
                    fn_args = dict(call.args or {})
                    logger.info("Executing tool '%s' with args %s", fn_name, fn_args)

                    tool_fn = tool_map.get(fn_name)
                    if not tool_fn:
                        tool_result = f"Error: Tool '{fn_name}' is not recognized."
                    else:
                        try:
                            if inspect.iscoroutinefunction(tool_fn):
                                tool_result = await tool_fn(**fn_args)
                            else:
                                tool_result = tool_fn(**fn_args)
                        except Exception as tool_exc:
                            logger.exception("Error executing tool %s: %s", fn_name, tool_exc)
                            tool_result = f"Tool execution failed with error: {tool_exc}"

                    execution_history.append({
                        "name": fn_name,
                        "args": fn_args,
                        "result": tool_result,
                    })

                    # Feed the tool response back to the conversation
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_function_response(
                                    name=fn_name,
                                    response={"result": tool_result},
                                )
                            ],
                        )
                    )

            # Fallback if loop exceeded max iterations
            return (
                response.text or "Max tool iterations reached during deliberation.",
                execution_history,
            )

        except Exception as exc:
            logger.error("Gemini tool execution pipeline failed: %s", exc, exc_info=True)
            raise GeminiAPIError(f"Gemini API tool execution error: {exc}") from exc
