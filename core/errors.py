"""Domain exceptions and error hierarchy for Personal AI Assistant."""


class AssistantBaseError(Exception):
    """Base exception for all assistant errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AssistantBaseError):
    """Raised when environment configuration is missing or invalid."""


class SecurityViolationError(AssistantBaseError):
    """Raised when an unauthorized user attempts to interact with the bot."""


class RateLimitExceededError(AssistantBaseError):
    """Raised when rate limits are exceeded."""

    def __init__(self, message: str = "Rate limit exceeded. Please wait a moment.", retry_after: float = 60.0) -> None:
        super().__init__(message, details={"retry_after": retry_after})
        self.retry_after = retry_after


class GeminiAPIError(AssistantBaseError):
    """Raised when an interaction with Google Gemini API fails."""


class OpenAIDispatcherError(AssistantBaseError):
    """Raised when an interaction with the OpenAI Dispatcher fails."""


class ConnectorError(AssistantBaseError):
    """Raised when a stream connector fails to fetch or parse upstream data."""
