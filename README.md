# LifeStream Personal AI Assistant 🤖

An agentic, multi-modal personal AI assistant operating on Telegram and powered by **Google Gemini 3.8 Flash**. The assistant unifies personal life-streams (finances, receipts, travel alerts, and emails) into a conversational, privacy-first interface.

---

## ✨ Features

- **Multimodal OCR & Document Parsing**: Send photos of physical receipts, bills, or flight tickets for automated data extraction and financial summaries.
- **Automated Tool Calling**: Gemini 3.8 Flash intelligently calls backend connectors (`query_balance`, `query_spending`, `query_recent_transactions`, `query_flight_status`, `query_urgent_emails`) dynamically to answer user questions.
- **Life Stream Connectors**:
  - 💰 **Monarch Money Connector**: Real-time balance tracking, budget monitoring, and transaction retrieval.
  - 📬 **Gmail Connector**: High-signal email scanning, flight tracking, and urgent notification digests.
- **Data Sanitization & Privacy Shield**: Masks sensitive information (credit card numbers, bank account numbers, passwords, SSNs) before data reaches the LLM context or logs.
- **Strict Authorization**: Whitelisted Telegram user IDs with custom Telegram message filters rejecting unauthorized interactions.
- **Rate Limiting & Safety**: Token-bucket sliding window rate limiter to keep API consumption predictable.

---

## 🏛️ Architecture

```
personal-ai-assistant/
├── agent/                  # Core Agent logic
│   ├── runner.py           # Orchestrates queries, Gemini tool loops, and multimodal inputs
│   ├── context.py          # Formats connector data into structured LLM contexts
│   └── prompts.py          # System instructions & task-specific prompt templates
├── bot/                    # Telegram Bot interface
│   ├── main.py             # Application builder, lifecycle handlers, long-polling entry point
│   ├── handlers.py         # /start, /status, /sync, text & photo message dispatchers
│   └── security.py         # Whitelist filter and @authorized_only decorator
├── connectors/             # Life Stream integrations
│   ├── base.py             # BaseConnector abstract class and ConnectorRegistry
│   ├── monarch.py          # Monarch Money financial connector & tools
│   ├── gmail.py            # Gmail alerts, receipts, and flight status connector
│   ├── models.py           # Strongly typed Event and Stream data structures
│   └── sanitization.py     # Regex-based PII / PCI redaction pipeline
├── core/                   # Shared foundational services
│   ├── config.py           # Pydantic Settings environment configuration
│   ├── gemini.py           # Async Gemini client using official google-genai SDK
│   ├── rate_limit.py       # Sliding-window user rate limiter
│   └── errors.py           # Custom exception hierarchy
├── tests/                  # Pytest test suite (100% async unit coverage)
├── pyproject.toml          # Project configuration and dependencies
└── .env.example            # Template environment variables
```

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.12 or higher
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API Key from [Google AI Studio](https://aistudio.google.com/)
- Your Telegram User ID (obtainable from [@userinfobot](https://t.me/userinfobot))

### 2. Installation

Clone the repository and set up a virtual environment:

```bash
git clone <your-repo-url>
cd personal-ai-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Environment Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```dotenv
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
GEMINI_API_KEY="your_gemini_api_key"
ALLOWED_TELEGRAM_USER_IDS="your_telegram_numeric_id"
GEMINI_MODEL="gemini-3.8-flash"
LOG_LEVEL="INFO"
RATE_LIMIT_CALLS_PER_MINUTE=30
```

---

## 🧪 Running Tests

The test suite contains 28 asynchronous tests covering connectors, prompt synthesis, agent tool loops, security filters, and Telegram dispatchers:

```bash
pytest
```

---

## 💻 Running the Assistant

### Local Interactive CLI (No Telegram Required)

You can test the agent and tools directly in your terminal:

```bash
python scripts/cli_chat.py
```

### Running the Telegram Bot

To start the bot daemon:

```bash
python -m bot.main
```

Then open Telegram and interact with your bot:
- `/start` - Introduction and usage guide
- `/status` - Connected streams, active model, and health status
- `/sync` - Fetch fresh event digest across all connected accounts
- Send a text message (e.g. *"What is my current net worth and recent spending?"*)
- Send a photo or receipt attachment for instant OCR parsing and extraction

### Running via Docker Compose

Run the bot as a background container:

```bash
docker compose up -d --build
```

View container logs:

```bash
docker compose logs -f
```

---

## 🛡️ Security & Privacy

1. **User Whitelist**: Only user IDs defined in `ALLOWED_TELEGRAM_USER_IDS` are permitted to issue commands or send messages. All other requests are denied.
2. **Local Sanitization**: Sensitive financial identifiers (account numbers, credit cards, credentials) are redacted via [`connectors/sanitization.py`](connectors/sanitization.py) before passing to the Gemini model.
