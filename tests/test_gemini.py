"""Unit tests for the GeminiClient wrapper."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from core.errors import GeminiAPIError
from core.gemini import GeminiClient


@pytest.mark.asyncio
async def test_gemini_generate_text_success() -> None:
    """Verify generate_text calls client.aio.models.generate_content and returns text."""
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Here is the financial summary for today."
    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    wrapper = GeminiClient(api_key="fake-key", model="gemini-3.8-flash", client=mock_genai_client)
    result = await wrapper.generate_text("Summarize my expenses.")

    assert result == "Here is the financial summary for today."
    mock_genai_client.aio.models.generate_content.assert_awaited_once()
    args, kwargs = mock_genai_client.aio.models.generate_content.call_args
    assert kwargs["model"] == "gemini-3.8-flash"
    assert kwargs["contents"] == "Summarize my expenses."


@pytest.mark.asyncio
async def test_gemini_generate_text_error_handling() -> None:
    """Verify exceptions from SDK are wrapped in GeminiAPIError."""
    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("Quota exceeded"))

    wrapper = GeminiClient(api_key="fake-key", model="gemini-3.8-flash", client=mock_genai_client)
    with pytest.raises(GeminiAPIError) as exc_info:
        await wrapper.generate_text("Hello")
    assert "Gemini API text generation error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_analyze_image_success() -> None:
    """Verify analyze_image constructs multimodal parts and returns OCR transcript."""
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Merchant: Whole Foods\nTotal: $42.50\nDate: Nov 8, 2026"
    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    wrapper = GeminiClient(api_key="fake-key", model="gemini-3.8-flash", client=mock_genai_client)
    image_bytes = b"fake_jpeg_image_data_bytes"
    result = await wrapper.analyze_image(image_bytes=image_bytes, mime_type="image/jpeg")

    assert "Whole Foods" in result
    assert "$42.50" in result
    mock_genai_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_generate_with_tools_execution() -> None:
    """Verify automated tool dispatch execution loop when function_calls are returned."""
    mock_genai_client = MagicMock()

    # Step 1: Model requests tool execution
    fn_call_mock = MagicMock()
    fn_call_mock.name = "query_bank"
    fn_call_mock.args = {"acct_id": "chase-1"}

    response_1 = MagicMock()
    response_1.function_calls = [fn_call_mock]
    cand_1 = MagicMock()
    cand_1.content = MagicMock()
    response_1.candidates = [cand_1]
    response_1.text = None

    # Step 2: Model returns final response after receiving tool result
    response_2 = MagicMock()
    response_2.function_calls = None
    response_2.text = "Your Chase account balance is $5,430."

    mock_genai_client.aio.models.generate_content = AsyncMock(side_effect=[response_1, response_2])

    async def query_bank(acct_id: str) -> str:
        return f"Balance for {acct_id}: $5,430"

    wrapper = GeminiClient(api_key="fake-key", model="gemini-3.8-flash", client=mock_genai_client)
    final_text, history = await wrapper.generate_with_tools(
        prompt="What is my bank balance?",
        tools=[query_bank],
    )

    assert final_text == "Your Chase account balance is $5,430."
    assert len(history) == 1
    assert history[0]["name"] == "query_bank"
    assert history[0]["result"] == "Balance for chase-1: $5,430"
    assert mock_genai_client.aio.models.generate_content.await_count == 2
