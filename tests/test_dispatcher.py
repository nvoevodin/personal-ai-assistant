"""Unit tests for the 3-Tier OpenAI Model Dispatcher."""

from unittest.mock import AsyncMock, MagicMock
import pytest
import openai

from core.dispatcher import (
    ModelDispatcher,
    ModelTier,
    TriageResult,
    DispatchResponse,
)
from core.errors import OpenAIDispatcherError


@pytest.fixture
def mock_openai_client() -> MagicMock:
    """Mock AsyncOpenAI client with mock chat completions create."""
    mock_client = MagicMock(spec=openai.AsyncOpenAI)
    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_completions.create = AsyncMock()
    mock_chat.completions = mock_completions
    mock_client.chat = mock_chat
    return mock_client


def test_tier_resolution_routing(mock_openai_client: MagicMock) -> None:
    """Verify tier routing rules for default, prefix escalation, and explicit overrides."""
    dispatcher = ModelDispatcher(client=mock_openai_client)

    # 1. Default conversational turns -> Tier 2 (gpt-6.1-terra)
    assert dispatcher.resolve_tier("What is my checking balance?") == ModelTier.TIER_2
    assert dispatcher.resolve_tier("Hello bot!") == ModelTier.TIER_2

    # 2. Escalation prefixes -> Tier 3 (gpt-6.1-sol)
    assert dispatcher.resolve_tier("/deep run a 5-year retirement forecast") == ModelTier.TIER_3
    assert dispatcher.resolve_tier("/audit analyze my quarterly tax deductions") == ModelTier.TIER_3
    assert dispatcher.resolve_tier("/solve optimize my loan repayment strategy") == ModelTier.TIER_3
    assert dispatcher.resolve_tier("  /DEEP case-insensitive prefix  ") == ModelTier.TIER_3

    # 3. Explicit tier overrides
    assert dispatcher.resolve_tier("hello", tier_override=ModelTier.TIER_1) == ModelTier.TIER_1
    assert dispatcher.resolve_tier("hello", tier_override="tier_1") == ModelTier.TIER_1
    assert dispatcher.resolve_tier("hello", tier_override="gpt-6-luna") == ModelTier.TIER_1
    assert dispatcher.resolve_tier("hello", tier_override="gpt-6.1-sol") == ModelTier.TIER_3


def test_trim_conversation_history() -> None:
    """Verify context trimming restricts history to bounded 10-turn window."""
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"} for i in range(30)]

    # 10 turns = 20 messages limit
    trimmed = ModelDispatcher.trim_conversation_history(history, max_turns=10)
    assert len(trimmed) == 20
    assert trimmed[0]["content"] == "msg 10"
    assert trimmed[-1]["content"] == "msg 29"

    # Empty or short history stays untouched
    assert ModelDispatcher.trim_conversation_history([]) == []
    short = [{"role": "user", "content": "hi"}]
    assert ModelDispatcher.trim_conversation_history(short) == short


def test_calculate_turn_cost() -> None:
    """Verify token cost calculation across all three pricing tiers."""
    # Tier 1 ($0.10/in, $0.50/out per 1M)
    cost_t1 = ModelDispatcher.calculate_turn_cost(ModelTier.TIER_1, prompt_tokens=10_000, completion_tokens=2_000)
    # (10,000 * 0.10 / 1M) + (2,000 * 0.50 / 1M) = 0.001 + 0.001 = 0.002
    assert cost_t1 == pytest.approx(0.002, abs=1e-5)

    # Tier 2 ($1.00/in, $5.00/out per 1M)
    cost_t2 = ModelDispatcher.calculate_turn_cost(ModelTier.TIER_2, prompt_tokens=10_000, completion_tokens=1_000)
    # (10,000 * 1.00 / 1M) + (1,000 * 5.00 / 1M) = 0.01 + 0.005 = 0.015
    assert cost_t2 == pytest.approx(0.015, abs=1e-5)

    # Tier 3 ($2.00/in, $10.00/out per 1M)
    cost_t3 = ModelDispatcher.calculate_turn_cost(ModelTier.TIER_3, prompt_tokens=5_000, completion_tokens=2_000)
    # (5,000 * 2.00 / 1M) + (2,000 * 10.00 / 1M) = 0.01 + 0.02 = 0.03
    assert cost_t3 == pytest.approx(0.03, abs=1e-5)


@pytest.mark.asyncio
async def test_dispatch_query_tier2_workhorse(mock_openai_client: MagicMock) -> None:
    """Verify standard queries route to Tier 2 (gpt-6.1-terra) with low reasoning effort."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Here is your spending breakdown."
    mock_choice.message.tool_calls = None

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 500
    mock_usage.completion_tokens = 100
    mock_usage.total_tokens = 600

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_openai_client.chat.completions.create.return_value = mock_response

    dispatcher = ModelDispatcher(client=mock_openai_client)
    res = await dispatcher.dispatch_query(
        user_message="Show my recent expenses",
        conversation_history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    )

    assert isinstance(res, DispatchResponse)
    assert res.tier == ModelTier.TIER_2
    assert res.model == "gpt-6.1-terra"
    assert res.content == "Here is your spending breakdown."
    assert res.total_tokens == 600
    assert res.estimated_cost_usd > 0

    # Verify call parameters sent to OpenAI SDK
    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-6.1-terra"
    assert call_kwargs["reasoning_effort"] == "low"
    assert len(call_kwargs["messages"]) == 3  # 2 history + 1 user


@pytest.mark.asyncio
async def test_dispatch_query_tier3_deep_analyst(mock_openai_client: MagicMock) -> None:
    """Verify /audit queries route to Tier 3 (gpt-6.1-sol) with high reasoning effort."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Comprehensive financial risk audit completed."
    mock_choice.message.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(prompt_tokens=2000, completion_tokens=1500, total_tokens=3500)

    mock_openai_client.chat.completions.create.return_value = mock_response

    dispatcher = ModelDispatcher(client=mock_openai_client)
    res = await dispatcher.dispatch_query(
        user_message="/audit Review all my credit card interest rates and debt risk",
    )

    assert res.tier == ModelTier.TIER_3
    assert res.model == "gpt-6.1-sol"
    assert "Comprehensive financial risk audit" in res.content

    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-6.1-sol"
    assert call_kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_evaluate_background_event_noise_gatekeeper(mock_openai_client: MagicMock) -> None:
    """Verify Tier 1 triage evaluates background event with JSON mode and suppresses noise."""
    triage_json = (
        '{"should_notify": false, "summary": "Promotional newsletter from Starbucks", '
        '"urgency": "low", "category": "noise"}'
    )
    mock_choice = MagicMock()
    mock_choice.message.content = triage_json
    mock_response = MagicMock(choices=[mock_choice], usage=MagicMock(prompt_tokens=200, completion_tokens=40))

    mock_openai_client.chat.completions.create.return_value = mock_response

    dispatcher = ModelDispatcher(client=mock_openai_client)
    result = await dispatcher.evaluate_background_event(
        event_text="50% off holiday lattes this Friday at Starbucks!"
    )

    assert isinstance(result, TriageResult)
    assert result.should_notify is False
    assert result.category == "noise"
    assert result.urgency == "low"

    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-6-luna"
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["temperature"] == 0.0


@pytest.mark.asyncio
async def test_evaluate_background_event_urgent_finance_alert(mock_openai_client: MagicMock) -> None:
    """Verify Tier 1 triage flags high-signal urgent alerts for user notification."""
    triage_json = (
        '{"should_notify": true, "summary": "Unusual $1,450 wire transfer debited from checking", '
        '"urgency": "high", "category": "finance"}'
    )
    mock_choice = MagicMock()
    mock_choice.message.content = triage_json
    mock_response = MagicMock(choices=[mock_choice], usage=MagicMock(prompt_tokens=300, completion_tokens=50))

    mock_openai_client.chat.completions.create.return_value = mock_response

    dispatcher = ModelDispatcher(client=mock_openai_client)
    result = await dispatcher.triage_notification(
        title="Outgoing Wire Confirmation",
        body="Your account was debited $1,450.00 for wire sequence 90123.",
        source="monarch",
    )

    assert result.should_notify is True
    assert result.urgency == "high"
    assert result.category == "finance"
    assert "Unusual $1,450 wire transfer" in result.summary


@pytest.mark.asyncio
async def test_extract_transaction_data(mock_openai_client: MagicMock) -> None:
    """Verify Tier 1 structured transaction extraction."""
    extracted_json = '{"merchant": "Target", "amount": 84.50, "date": "2026-11-09", "category": "Groceries"}'
    mock_choice = MagicMock()
    mock_choice.message.content = extracted_json
    mock_response = MagicMock(choices=[mock_choice], usage=MagicMock(prompt_tokens=150, completion_tokens=30))

    mock_openai_client.chat.completions.create.return_value = mock_response

    dispatcher = ModelDispatcher(client=mock_openai_client)
    data = await dispatcher.extract_transaction_data("Target Store #1029 84.50 USD on Nov 9")

    assert data["merchant"] == "Target"
    assert data["amount"] == 84.50
    assert data["category"] == "Groceries"


@pytest.mark.asyncio
async def test_dispatch_error_handling(mock_openai_client: MagicMock) -> None:
    """Verify OpenAI SDK errors are caught and converted to OpenAIDispatcherError."""
    mock_openai_client.chat.completions.create.side_effect = openai.RateLimitError(
        message="Rate limit exceeded", response=MagicMock(status_code=429), body=None
    )

    dispatcher = ModelDispatcher(client=mock_openai_client)
    with pytest.raises(OpenAIDispatcherError) as exc_info:
        await dispatcher.dispatch_query("Hello bot")

    assert "rate limit" in str(exc_info.value).lower()
