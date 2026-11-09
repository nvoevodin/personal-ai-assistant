"""Base connector interface and registry for pluggable life-stream collectors."""

from abc import ABC, abstractmethod
from typing import Any
from connectors.models import LifeStreamType, StreamEvent


class BaseConnector(ABC):
    """Abstract Base Class for all external life-stream connectors."""

    def __init__(self, name: str, stream_type: LifeStreamType) -> None:
        self.name = name
        self.stream_type = stream_type
        self.is_connected = False

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection or authenticate with external service."""

    @abstractmethod
    async def fetch_events(self, limit: int = 10) -> list[StreamEvent]:
        """Poll and return a normalized list of sanitized StreamEvent models."""

    @abstractmethod
    async def get_health(self) -> dict[str, Any]:
        """Return connectivity status and diagnostic health metrics."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully release network sockets or session resources."""


class ConnectorRegistry:
    """Central registry facilitating self-improvement and dynamic tool integration."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register an active connector instance."""
        self._connectors[connector.name] = connector

    def get(self, name: str) -> BaseConnector | None:
        """Retrieve a registered connector by name."""
        return self._connectors.get(name)

    def all_connectors(self) -> list[BaseConnector]:
        """Return all registered connectors."""
        return list(self._connectors.values())

    async def connect_all(self) -> None:
        """Initialize all registered connectors in parallel."""
        for conn in self._connectors.values():
            if not conn.is_connected:
                await conn.connect()

    async def fetch_all_events(self, limit_per_connector: int = 10) -> list[StreamEvent]:
        """Fetch and aggregate normalized events from all active connectors."""
        aggregated: list[StreamEvent] = []
        for conn in self._connectors.values():
            try:
                events = await conn.fetch_events(limit=limit_per_connector)
                aggregated.extend(events)
            except Exception as exc:
                # Isolate connector failures so one faulty upstream doesn't crash all streams
                aggregated.append(
                    StreamEvent(
                        id=f"error-{conn.name}",
                        stream_type=conn.stream_type,
                        source=conn.name,
                        title=f"{conn.name} Ingestion Failed",
                        summary=f"Connector encountered an exception: {exc}",
                        is_urgent=True,
                    )
                )
        # Sort descending by timestamp
        aggregated.sort(key=lambda e: e.timestamp, reverse=True)
        return aggregated
