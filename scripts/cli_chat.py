"""Interactive terminal CLI for testing the Personal AI Assistant locally without Telegram."""

import asyncio
import os
import sys
from dotenv import load_dotenv

from agent.runner import AgentRunner
from connectors.base import ConnectorRegistry
from connectors.gmail import GmailConnector
from connectors.monarch import MonarchConnector
from core.config import get_settings
from core.gemini import GeminiClient
from core.rate_limit import RateLimiter


async def main() -> None:
    load_dotenv()
    print("=" * 60)
    print("🤖 LifeStream Personal AI Assistant - Local Interactive CLI")
    print("=" * 60)

    try:
        settings = get_settings()
    except Exception as exc:
        print(f"⚠️ Configuration error: {exc}")
        print("Please ensure .env contains GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, and ALLOWED_TELEGRAM_USER_IDS.")
        return

    print(f"• Active Model: {settings.gemini_model}")
    print("• Initializing LifeStream Connectors...")

    registry = ConnectorRegistry()
    registry.register(MonarchConnector())
    registry.register(GmailConnector())
    await registry.connect_all()

    client = GeminiClient(
        api_key=settings.gemini_api_key_value,
        model=settings.gemini_model,
    )
    runner = AgentRunner(
        gemini_client=client,
        registry=registry,
        rate_limiter=RateLimiter(max_calls=60),
    )

    print("\n✅ System ready. Type 'exit' or 'quit' to stop.")
    print("Sample queries:")
    print("  - 'What are my current account balances and recent spending?'")
    print("  - 'Do I have any urgent emails or flight updates?'")
    print("  - 'Summarize my financial health.'\n")

    while True:
        try:
            user_input = input("You > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break

            print("\n🤖 Thinking...", end="\r")
            response = await runner.handle_user_query(user_id=1, query=user_input)
            print(f"\nAssistant > {response}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break
        except Exception as err:
            print(f"\n⚠️ Error: {err}\n")


if __name__ == "__main__":
    asyncio.run(main())
