"""3-Tier OpenAI Model Dispatcher for Telegram Bot.

Dynamically routes incoming requests and background tasks across an OpenAI model hierarchy:
- Tier 1 (gpt-6-luna): High-Speed Router, Extraction, and Noise Gatekeeper (JSON mode, $0.10/$0.50 per 1M).
- Tier 2 (gpt-6.1-terra): Default Brain & Daily Workhorse (Conversational, tool calling, $1.00/$5.00 per 1M).
- Tier 3 (gpt-6.1-sol): Frontier Deep Analyst (Deep reasoning, financial audits & simulations, $2.00/$10.00 per 1M).
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Callable, Literal

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

from core.config import Settings, get_settings
from core.errors import OpenAIDispatcherError

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    """3-Tier Model Hierarchy classification."""

    TIER_1 = "tier_1"  # gpt-6-luna: High-Speed Router & Noise Gatekeeper
    TIER_2 = "tier_2"  # gpt-6.1-terra: Default Brain & Daily Workhorse
    TIER_3 = "tier_3"  # gpt-6.1-sol: Frontier Deep Analyst


# Blended token pricing per 1M tokens ($ USD)
TIER_PRICING: dict[ModelTier, dict[str, float]] = {
    ModelTier.TIER_1: {"input_per_m": 0.10, "output_per_m": 0.50},
    ModelTier.TIER_2: {"input_per_m": 1.00, "output_per_m": 5.00},
    ModelTier.TIER_3: {"input_per_m": 2.00, "output_per_m": 10.00},
}

# Prefix commands that explicitly escalate execution to Tier 3 Frontier Analyst
DEEP_COMMAND_PREFIXES = ("/deep", "/audit", "/solve")

ANALYST_SYSTEM_PROMPT = """You are a sharp, skeptical personal financial & operations advisor.
You have received a flagged life-stream event that passed initial noise filtering.
You are given the user's current financial snapshot (account balances, checking liquidity, upcoming bills, and recent transactions).

BEFORE deciding to notify the user on Telegram:
1. INVESTIGATE & CROSS-CHECK:
   - Check account balances, checking liquidity, recurring obligations, and recent transactions.
   - For transfers: look at the direction (+ into account vs - out of account) and source/destination. Do not reverse transfers!
   - For bills/payments: check whether it's an auto-pay, if checking balance covers it, or if it's already accounted for.
   - For deliveries/statements: check if this requires actual user action or intervention.
2. CHALLENGE & VERIFY:
   - Is this a duplicate charge, price increase on a recurring bill, or refund discrepancy?
   - Is checking balance sufficient for upcoming auto-pays or at risk of overdraft?
   - Is there a smarter financial move or catch the user might miss?
3. GATEKEEP SILENCE:
   - If everything is normal, expected, routine, or requires zero action (e.g., routine statement availability with no balance issues, standard package transit milestones, expected recurring subscription within budget), output ONLY:
     NO_ACTION_REQUIRED
   - Do NOT send a generic summary if there is no actionable insight or anomaly.
4. BE DIRECT & OPINIONATED:
   - If you DO alert the user, write a concise, sharp executive advisory.
   - Lead directly with the insight, anomaly, risk, or recommended action—never parrot raw email or transaction text.
   - Format cleanly using Markdown (use bolding, bullet points, but NO markdown pipe tables; use text blocks if needed).
"""


class TriageResult(BaseModel):
    """Structured noise gatekeeper and triage evaluation for background stream events."""

    should_notify: bool = Field(
        ...,
        description="Whether this background event warrants an immediate Telegram alert or deeper investigation",
    )
    needs_investigation: bool = Field(
        default=False,
        description="Whether this event should be passed to Tier 2 Analyst for deep investigation before alerting",
    )
    summary: str = Field(
        ...,
        description="Concise 1-2 sentence executive briefing of the event",
    )
    urgency: Literal["low", "medium", "high"] = Field(
        ...,
        description="Priority level of the notification",
    )
    category: Literal["finance", "order_tracking", "calendar", "noise"] = Field(
        ...,
        description="Category classification of the event",
    )

    @model_validator(mode="before")
    @classmethod
    def set_needs_investigation(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "needs_investigation" not in data and "should_notify" in data:
                data["needs_investigation"] = data["should_notify"]
        return data


class DispatchResponse(BaseModel):
    """Encapsulates completed model response, tokens burned, and accounting metadata."""

    content: str = Field(default="", description="Natural language message response")
    model: str = Field(..., description="Target model identifier invoked")
    tier: ModelTier = Field(..., description="Model tier routed to")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, description="Raw tool calls emitted by model")
    prompt_tokens: int = Field(default=0, description="Input prompt tokens consumed")
    completion_tokens: int = Field(default=0, description="Output generation tokens consumed")
    total_tokens: int = Field(default=0, description="Total tokens consumed in turn")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated USD cost for the turn")


class ModelDispatcher:
    """Asynchronous 3-tier OpenAI model dispatcher engine for personal assistant operations."""

    def __init__(
        self,
        api_key: str | None = None,
        client: AsyncOpenAI | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        resolved_api_key = api_key or self._settings.openai_api_key_value

        # Support dependency injection for unit testing without live network calls
        if client is not None:
            self.client = client
        else:
            self.client = AsyncOpenAI(api_key=resolved_api_key or "sk-dummy-key-for-init")

        # Configurable model mappings
        self.tier_models: dict[ModelTier, str] = {
            ModelTier.TIER_1: self._settings.openai_tier1_model,
            ModelTier.TIER_2: self._settings.openai_tier2_model,
            ModelTier.TIER_3: self._settings.openai_tier3_model,
        }

    def resolve_tier(
        self,
        user_message: str,
        tier_override: ModelTier | str | None = None,
    ) -> ModelTier:
        """Resolve target model tier based on override, prompt commands, or default chat policy."""
        if tier_override:
            if isinstance(tier_override, str):
                try:
                    return ModelTier(tier_override)
                except ValueError:
                    # Match by model name string if passed directly
                    for t, m in self.tier_models.items():
                        if tier_override == m or tier_override == t.value:
                            return t
                    return ModelTier.TIER_2
            return tier_override

        clean_msg = user_message.strip().lower()
        # Route to Tier 3 if prompt starts with escalation commands
        if any(clean_msg.startswith(prefix) for prefix in DEEP_COMMAND_PREFIXES):
            return ModelTier.TIER_3

        # Default all interactive chat traffic to Tier 2 Workhorse
        return ModelTier.TIER_2

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        """Return True if model is a reasoning-class model enforcing default temperature."""
        lowered = model_name.lower()
        return any(lowered.startswith(prefix) for prefix in ("gpt-6", "o1", "o3", "o4"))

    @staticmethod
    def trim_conversation_history(
        conversation_history: list[dict[str, str]] | None,
        max_turns: int = 10,
    ) -> list[dict[str, str]]:
        """Trim message history to keep rolling context within bounded turn window.

        Args:
            conversation_history: Chronological list of message dicts (role, content).
            max_turns: Maximum conversation turns (user/assistant pairs) to preserve.
        """
        if not conversation_history:
            return []
        # Keep up to 2 * max_turns messages (e.g. 10 user + 10 assistant turns)
        limit = max_turns * 2
        return conversation_history[-limit:]

    @staticmethod
    def calculate_turn_cost(tier: ModelTier, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated USD cost based on published tier token rates."""
        rates = TIER_PRICING.get(tier, {"input_per_m": 1.0, "output_per_m": 5.0})
        cost = (prompt_tokens / 1_000_000.0 * rates["input_per_m"]) + (
            completion_tokens / 1_000_000.0 * rates["output_per_m"]
        )
        return round(cost, 6)

    async def dispatch_query(
        self,
        user_message: str,
        conversation_history: list[dict[str, str]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tier_override: ModelTier | str | None = None,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_turns: int = 10,
    ) -> DispatchResponse:
        """Execute a conversational completion routed to the appropriate OpenAI model tier.

        Args:
            user_message: Incoming user text query or instruction.
            conversation_history: Optional preceding conversational memory turns.
            tools: Optional OpenAI-format function definitions for tool calling.
            tier_override: Optional manual tier assignment.
            system_instruction: Optional system instruction prompt.
            temperature: Optional sampling temperature override.
            max_turns: Rolling history window limit.

        Returns:
            DispatchResponse containing content, token statistics, and cost estimates.
        """
        tier = self.resolve_tier(user_message=user_message, tier_override=tier_override)
        model = self.tier_models[tier]

        # 1. Prepare message payload with rolling history trimming
        messages: list[dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        trimmed_history = self.trim_conversation_history(conversation_history, max_turns=max_turns)
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": user_message})

        # 2. Configure Tier-specific execution styles
        is_reasoning = self._is_reasoning_model(model)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }

        if tier == ModelTier.TIER_1:
            # Deterministic extraction
            if not is_reasoning:
                kwargs["temperature"] = 0.0 if temperature is None else temperature
        elif tier == ModelTier.TIER_2:
            # Fast conversational, minimal reasoning tokens to reduce latency
            if not is_reasoning:
                kwargs["temperature"] = 0.3 if temperature is None else temperature
            kwargs["reasoning_effort"] = "low"
        elif tier == ModelTier.TIER_3:
            # Frontier deep reasoning
            kwargs["reasoning_effort"] = "high"
            if temperature is not None and not is_reasoning:
                kwargs["temperature"] = temperature

        if tools:
            kwargs["tools"] = tools

        # 3. Call OpenAI API with error handling and cost telemetry
        try:
            logger.info("Dispatching query to %s [%s] (history len: %d)", tier.value, model, len(trimmed_history))
            try:
                response = await self.client.chat.completions.create(**kwargs)
            except openai.BadRequestError as bad_req:
                err_msg = str(bad_req).lower()
                retried = False
                if "temperature" in err_msg and "temperature" in kwargs:
                    logger.warning("Model %s rejected temperature; retrying with model default", model)
                    kwargs.pop("temperature", None)
                    retried = True
                if "reasoning_effort" in err_msg and "reasoning_effort" in kwargs:
                    logger.warning("Model %s rejected reasoning_effort; retrying without it", model)
                    kwargs.pop("reasoning_effort", None)
                    retried = True
                if retried:
                    response = await self.client.chat.completions.create(**kwargs)
                else:
                    raise

            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract tool calls if emitted
            raw_tool_calls: list[dict[str, Any]] = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    raw_tool_calls.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })

            # Usage accounting
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            total_tokens = response.usage.total_tokens if response.usage else 0
            cost_usd = self.calculate_turn_cost(tier, prompt_tokens, completion_tokens)

            logger.info(
                "OpenAI [%s / %s] finished | Tokens: %d prompt, %d completion (%d total) | Est Cost: $%.6f",
                tier.value,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost_usd,
            )

            return DispatchResponse(
                content=content,
                model=model,
                tier=tier,
                tool_calls=raw_tool_calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=cost_usd,
            )

        except openai.RateLimitError as err:
            logger.error("OpenAI Rate limit exceeded on %s: %s", model, err)
            raise OpenAIDispatcherError(f"OpenAI rate limit / quota exceeded on {model}: {err}") from err
        except openai.APITimeoutError as err:
            logger.error("OpenAI request timed out on %s: %s", model, err)
            raise OpenAIDispatcherError(f"OpenAI API call timed out on {model}: {err}") from err
        except openai.APIConnectionError as err:
            logger.error("OpenAI connection failure: %s", err)
            raise OpenAIDispatcherError(f"Cannot connect to OpenAI API: {err}") from err
        except openai.APIStatusError as err:
            logger.error("OpenAI status error [%s]: %s", err.status_code, err)
            raise OpenAIDispatcherError(f"OpenAI API status error {err.status_code}: {err.message}") from err
        except Exception as exc:
            logger.error("Unexpected error during OpenAI dispatch on %s: %s", model, exc, exc_info=True)
            raise OpenAIDispatcherError(f"OpenAI dispatch execution failed: {exc}") from exc

    async def evaluate_background_event(self, event_text: str) -> TriageResult:
        """Triage an incoming background life-stream event using Tier 1 (gpt-6-luna) in JSON mode.

        Evaluates incoming raw items from Monarch Money, Gmail receipts, or package tracking
        to determine whether an alert should wake or notify the user.

        Args:
            event_text: Raw event payload, email snippet, or transaction note.

        Returns:
            TriageResult with notification decision, executive summary, and urgency.
        """
        model = self.tier_models[ModelTier.TIER_1]
        system_prompt = (
            "You are an elite, noise-gatekeeper and triage router for an executive personal assistant.\n"
            "Analyze the provided life-stream event (financial transaction, email alert, delivery, or notification).\n"
            "Determine if this event warrants investigation or an alert to the user.\n\n"
            "Rules for triage:\n"
            "- Noise, routine promotional newsletters, standard shipping milestones, and mundane minor updates must have should_notify: false, needs_investigation: false.\n"
            "- Important financial transactions, unusual charges, security warnings, travel changes, or critical deliveries have needs_investigation: true, should_notify: true.\n"
            "- Output strictly valid JSON conforming to the schema:\n"
            "{\n"
            '  "should_notify": boolean,\n'
            '  "needs_investigation": boolean,\n'
            '  "summary": "concise 1-2 sentence executive briefing",\n'
            '  "urgency": "low" | "medium" | "high",\n'
            '  "category": "finance" | "order_tracking" | "calendar" | "noise"\n'
            "}"
        )

        try:
            logger.info("Evaluating background event with Tier 1 [%s]...", model)
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Event to triage:\n{event_text}"},
                ],
                "response_format": {"type": "json_object"},
            }
            if not self._is_reasoning_model(model):
                kwargs["temperature"] = 0.0

            try:
                response = await self.client.chat.completions.create(**kwargs)
            except openai.BadRequestError as bad_req:
                if "temperature" in str(bad_req).lower() and "temperature" in kwargs:
                    kwargs.pop("temperature", None)
                    response = await self.client.chat.completions.create(**kwargs)
                else:
                    raise

            raw_json = response.choices[0].message.content or "{}"
            data = json.loads(raw_json)

            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            cost = self.calculate_turn_cost(ModelTier.TIER_1, prompt_tokens, completion_tokens)
            logger.info("Triage complete via %s | Notifiable: %s | Cost: $%.6f", model, data.get("should_notify"), cost)

            return TriageResult.model_validate(data)

        except (json.JSONDecodeError, KeyError, ValueError) as parse_err:
            logger.warning("Tier 1 output parsing error (%s). Falling back to safe triage", parse_err)
            return TriageResult(
                should_notify=False,
                summary=event_text[:120],
                urgency="low",
                category="noise",
            )
        except Exception as exc:
            logger.error("Tier 1 event evaluation failed: %s", exc, exc_info=True)
            raise OpenAIDispatcherError(f"Tier 1 event evaluation failed: {exc}") from exc

    async def triage_notification(
        self,
        title: str,
        body: str,
        source: str = "generic",
    ) -> TriageResult:
        """Convenience method to triage a titled notification from any life stream."""
        formatted = f"Source: {source.upper()}\nTitle: {title}\nDetails: {body}"
        return await self.evaluate_background_event(event_text=formatted)

    async def investigate_and_advise(
        self,
        event_payload: str,
        context_block: str = "",
    ) -> str | None:
        """Investigate a flagged event against live context using Tier 2 (gpt-6.1-terra).

        Args:
            event_payload: Raw event or triage payload string.
            context_block: Live financial context (balances, upcoming obligations, transactions).

        Returns:
            Actionable advisory message string if notification is warranted, or None if
            the event is routine and Tier 2 determined 'NO_ACTION_REQUIRED'.
        """
        user_message = (
            f"FLAGGED EVENT TO INVESTIGATE:\n{event_payload}\n\n"
            f"LIVE FINANCIAL & LIFE-STREAM CONTEXT:\n{context_block}\n\n"
            "Evaluate whether this event requires user notification or intervention. "
            "If normal/routine/expected, output NO_ACTION_REQUIRED. Otherwise, provide a direct executive advisory."
        )
        try:
            logger.info("Escalating flagged event to Tier 2 Analyst for investigation...")
            response = await self.dispatch_query(
                user_message=user_message,
                tier_override=ModelTier.TIER_2,
                system_instruction=ANALYST_SYSTEM_PROMPT.strip(),
            )
            content = response.content.strip()
            if not content or "NO_ACTION_REQUIRED" in content.upper():
                logger.info("Tier 2 Analyst decided NO_ACTION_REQUIRED. Alert suppressed.")
                return None
            return content
        except Exception as exc:
            logger.error("Tier 2 Analyst investigation failed: %s", exc, exc_info=True)
            return None

    async def extract_transaction_data(self, raw_text: str) -> dict[str, Any]:
        """Extract structured financial data from raw notes or receipts using Tier 1 (gpt-6-luna)."""
        model = self.tier_models[ModelTier.TIER_1]
        system_prompt = (
            "Extract structured financial data from the text.\n"
            "Return valid JSON with keys: merchant (str), amount (float or null), "
            "date (YYYY-MM-DD or null), category (str), currency (default USD)."
        )
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": raw_text},
                ],
                "response_format": {"type": "json_object"},
            }
            if not self._is_reasoning_model(model):
                kwargs["temperature"] = 0.0

            try:
                response = await self.client.chat.completions.create(**kwargs)
            except openai.BadRequestError as bad_req:
                if "temperature" in str(bad_req).lower() and "temperature" in kwargs:
                    kwargs.pop("temperature", None)
                    response = await self.client.chat.completions.create(**kwargs)
                else:
                    raise

            raw = response.choices[0].message.content or "{}"
            return json.loads(raw)
        except Exception as exc:
            logger.error("Tier 1 extraction failed: %s", exc)
            return {"error": str(exc), "raw": raw_text}
