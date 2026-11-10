"""UX Presentation Styles and Layout Presets."""

from dataclasses import dataclass
from enum import Enum


class UXStylePreset(str, Enum):
    """Available presentation profiles for formatting assistant responses."""
    EXECUTIVE = "executive"      # 🎩 Executive Butler: Polished, structured, TL;DR + insights
    MINIMALIST = "minimalist"    # ⚡ Minimalist: Hyper-dense metrics, zero conversational fluff
    ANALYTICAL = "analytical"    # 📊 Deep Analyst: Multi-metric financial audits and projections


@dataclass(frozen=True)
class StyleConfig:
    """Configuration attributes governing layout rendering for a preset."""
    id: UXStylePreset
    name: str
    emoji: str
    description: str
    include_salutation: bool
    include_insights: bool
    include_metadata_footer: bool
    divider_char: str = "─"


STYLE_REGISTRY: dict[UXStylePreset, StyleConfig] = {
    UXStylePreset.EXECUTIVE: StyleConfig(
        id=UXStylePreset.EXECUTIVE,
        name="Executive Butler",
        emoji="🎩",
        description="Polished executive briefing with clear summary, monospace cards, and recommendations.",
        include_salutation=True,
        include_insights=True,
        include_metadata_footer=True,
    ),
    UXStylePreset.MINIMALIST: StyleConfig(
        id=UXStylePreset.MINIMALIST,
        name="Minimalist Dashboard",
        emoji="⚡",
        description="Dense, zero-fluff data cards and key bullet points only.",
        include_salutation=False,
        include_insights=False,
        include_metadata_footer=False,
    ),
    UXStylePreset.ANALYTICAL: StyleConfig(
        id=UXStylePreset.ANALYTICAL,
        name="Deep Analyst",
        emoji="📊",
        description="In-depth breakdown with percentage deltas, risk assessment, and long-horizon projection.",
        include_salutation=False,
        include_insights=True,
        include_metadata_footer=True,
    ),
}


def get_style_config(preset: str | UXStylePreset) -> StyleConfig:
    """Resolve StyleConfig from string name or enum, defaulting to Executive."""
    if isinstance(preset, str):
        try:
            preset = UXStylePreset(preset.lower())
        except ValueError:
            preset = UXStylePreset.EXECUTIVE
    return STYLE_REGISTRY.get(preset, STYLE_REGISTRY[UXStylePreset.EXECUTIVE])
