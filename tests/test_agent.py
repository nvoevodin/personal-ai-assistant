"""Unit tests for the agent context builder, tool runner, and rate limiter."""

import pytest
from agent.context import LifeStreamContextBuilder
from agent.runner import AgentRunner
from connectors.base import ConnectorRegistry
from connectors.monarch import MonarchConnector
from core.errors import RateLimitExceededError
from core.gemini import GeminiClient
from core.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_context_builder_formats_events(mock_registry: ConnectorRegistry) -> None:
    """Verify context builder groups urgent vs normal stream items into Markdown."""
    builder = LifeStreamContextBuilder(registry=mock_registry)
    context_str = await builder.build_context_block(max_events=10)

    assert "Current Life Stream Snapshot" in context_str
    assert "URGENT ALERTS" in context_str or "RECENT AMBIENT ACTIVITY" in context_str


@pytest.mark.asyncio
async def test_agent_runner_handle_user_query(
    mock_gemini_client: GeminiClient, mock_registry: ConnectorRegistry, tmp_path: pytest.TempPathFactory
) -> None:
    """Verify AgentRunner processes user query, invokes Gemini with tools, and returns response."""
    from storage.db import DatabaseManager

    test_db = DatabaseManager(db_path=str(tmp_path / "query_test.db"))
    runner = AgentRunner(gemini_client=mock_gemini_client, registry=mock_registry, db=test_db)
    response = await runner.handle_user_query(user_id=111222333, query="How much did I spend at Whole Foods?")

    assert response == "Processed response with financial tools."
    mock_gemini_client.generate_with_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_runner_multi_turn_history(
    mock_gemini_client: GeminiClient, mock_registry: ConnectorRegistry, tmp_path: pytest.TempPathFactory
) -> None:
    """Verify multi-turn queries pass historical conversational context into prompt."""
    from storage.db import DatabaseManager

    test_db = DatabaseManager(db_path=str(tmp_path / "test_memory.db"))
    runner = AgentRunner(gemini_client=mock_gemini_client, registry=mock_registry, db=test_db)

    # First turn
    await runner.handle_user_query(user_id=42, query="What is my checking balance?")
    # Second turn
    await runner.handle_user_query(user_id=42, query="What about my credit card?")

    assert mock_gemini_client.generate_with_tools.await_count == 2
    last_call_prompt = mock_gemini_client.generate_with_tools.call_args_list[1].kwargs["prompt"]
    assert "Recent Conversation History:" in last_call_prompt
    assert "What is my checking balance?" in last_call_prompt


@pytest.mark.asyncio
async def test_agent_runner_handle_photo(
    mock_gemini_client: GeminiClient, mock_registry: ConnectorRegistry, tmp_path: pytest.TempPathFactory
) -> None:
    """Verify AgentRunner processes photo attachment via Gemini multimodal OCR."""
    from storage.db import DatabaseManager

    test_db = DatabaseManager(db_path=str(tmp_path / "photo_test.db"))
    runner = AgentRunner(gemini_client=mock_gemini_client, registry=mock_registry, db=test_db)
    fake_photo = b"fake_photo_bytes_data"
    result = await runner.handle_photo_analysis(
        user_id=111222333,
        image_bytes=fake_photo,
        user_caption="Here is my receipt from yesterday",
    )

    assert "Whole Foods" in result
    mock_gemini_client.analyze_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limiter_throttling() -> None:
    """Verify RateLimiter permits allowed calls and throws RateLimitExceededError when exceeded."""
    limiter = RateLimiter(max_calls=2, window_seconds=60.0)
    user_id = 999

    assert await limiter.acquire(user_id) is True
    assert await limiter.acquire(user_id) is True

    with pytest.raises(RateLimitExceededError) as exc_info:
        await limiter.acquire(user_id)

    assert exc_info.value.retry_after > 0
    await limiter.reset(user_id)
    assert await limiter.acquire(user_id) is True
