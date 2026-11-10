"""LifeStream UX Presentation & Self-Improvement Subsystem."""

from ux.styles import UXStylePreset, StyleConfig, get_style_config, STYLE_REGISTRY
from ux.layout import (
    format_header,
    format_kpi_bar,
    format_ascii_table,
    format_financial_accounts,
    format_transactions_card,
    format_insights_block,
    format_alert_card,
    format_footer,
    format_executive_response,
    DIVIDER_LINE,
)
from ux.prompts import build_system_instruction, UX_RESPONSE_RULES
from ux.feedback import (
    get_ux_feedback_keyboard,
    get_style_picker_keyboard,
    handle_ux_callback,
    ux_command,
)

__all__ = [
    "UXStylePreset",
    "StyleConfig",
    "get_style_config",
    "STYLE_REGISTRY",
    "format_header",
    "format_kpi_bar",
    "format_ascii_table",
    "format_financial_accounts",
    "format_transactions_card",
    "format_insights_block",
    "format_alert_card",
    "format_footer",
    "format_executive_response",
    "DIVIDER_LINE",
    "build_system_instruction",
    "UX_RESPONSE_RULES",
    "get_ux_feedback_keyboard",
    "get_style_picker_keyboard",
    "handle_ux_callback",
    "ux_command",
]
