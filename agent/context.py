"""Life-stream context builder aggregating real-time data across connectors."""

from datetime import datetime, timezone
from connectors.base import ConnectorRegistry
from connectors.models import LifeStreamType, StreamEvent


class LifeStreamContextBuilder:
    """Aggregates and formats normalized connector events into dynamic LLM context."""

    def __init__(self, registry: ConnectorRegistry) -> None:
        self.registry = registry

    async def build_context_block(self, max_events: int = 15) -> str:
        """Fetch latest events from registered connectors and format into a Markdown prompt block."""
        events: list[StreamEvent] = await self.registry.fetch_all_events(limit_per_connector=max_events)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if not events:
            return f"### Current Life Stream Context (Timestamp: {now_str})\n*No recent events detected across monitored streams.*"

        urgent_events = [e for e in events if e.is_urgent]
        normal_events = [e for e in events if not e.is_urgent]

        lines = [
            f"### Current Life Stream Snapshot (Recorded: {now_str})",
            "",
        ]

        if urgent_events:
            lines.append("⚠️ **URGENT ALERTS / CRITICAL STREAM EVENTS:**")
            for ev in urgent_events:
                ts = ev.timestamp.strftime("%b %d %H:%M")
                lines.append(f"- `[{ev.stream_type.value.upper()}]` **{ev.title}** ({ts}): {ev.summary}")
            lines.append("")

        lines.append("📋 **RECENT AMBIENT ACTIVITY:**")
        for ev in normal_events[:10]:
            ts = ev.timestamp.strftime("%b %d %H:%M")
            lines.append(f"- `[{ev.stream_type.value.upper()}]` {ev.summary} ({ts})")

        return "\n".join(lines)
