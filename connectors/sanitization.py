"""PII (Personally Identifiable Information) scrubber and data sanitizer.

Ensures sensitive customer identifiers, passwords, tokens, and raw financial
account numbers are sanitized prior to being fed into model context.
"""

import re
from typing import Any

# Regex patterns for high-sensitivity data
CREDIT_CARD_REGEX = re.compile(
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\b"
)
SSN_REGEX = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
EMAIL_BEARER_TOKEN_REGEX = re.compile(
    r"(?i)\b(bearer\s+[a-zA-Z0-9_\-\.]{16,}|token[:=]\s*[a-zA-Z0-9_\-\.]{16,}|password[:=]\s*\S+)"
)
RAW_ACCOUNT_NUM_REGEX = re.compile(r"\b(account|acct|routing)(?:\s*(?:#|num|number)?\s*[:=]?\s*)(\d{6,17})\b", re.IGNORECASE)

SENSITIVE_KEY_NAMES = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "ssn",
    "cvv",
    "cvv2",
    "pin",
}


def sanitize_text(text: str) -> str:
    """Scrub sensitive PII (credit cards, SSNs, API tokens, raw bank accounts) from a string."""
    if not text:
        return ""

    # Mask SSNs
    text = SSN_REGEX.sub("[REDACTED_SSN]", text)

    # Mask Credit Cards (leave last 4 if matching)
    def _mask_cc(match: re.Match[str]) -> str:
        val = match.group(0).replace(" ", "").replace("-", "")
        return f"****-****-****-{val[-4:]}"

    text = CREDIT_CARD_REGEX.sub(_mask_cc, text)

    # Mask raw account numbers
    def _mask_acct(match: re.Match[str]) -> str:
        prefix = match.group(1)
        acct_val = match.group(2)
        return f"{prefix} ****{acct_val[-4:]}"

    text = RAW_ACCOUNT_NUM_REGEX.sub(_mask_acct, text)

    # Mask bearer tokens and passwords
    text = EMAIL_BEARER_TOKEN_REGEX.sub("[REDACTED_CREDENTIAL]", text)

    return text


def sanitize_payload(payload: Any) -> Any:
    """Recursively scrub sensitive keys and patterns from dicts, lists, or primitive types."""
    if isinstance(payload, dict):
        sanitized_dict: dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = str(key).lower()
            if any(sensitive in key_lower for sensitive in SENSITIVE_KEY_NAMES):
                sanitized_dict[key] = "[REDACTED]"
            else:
                sanitized_dict[key] = sanitize_payload(value)
        return sanitized_dict

    if isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]

    if isinstance(payload, str):
        return sanitize_text(payload)

    return payload
