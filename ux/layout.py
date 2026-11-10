"""High-fidelity Telegram response formatting and visual hierarchy engine."""

from typing import Any
from ux.styles import UXStylePreset, get_style_config

DIVIDER_LINE = "────────────────────────────────────"
SECTION_DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


def format_header(
    title: str,
    badge: str = "BRIEFING",
    emoji: str = "🎩",
    subtitle: str | None = None,
) -> str:
    """Render a polished, executive header block."""
    sub_text = f"\n_{subtitle}_" if subtitle else ""
    return f"{emoji} **[{badge.upper()}] {title}**{sub_text}\n{DIVIDER_LINE}"


def format_kpi_bar(metrics: list[tuple[str, str]]) -> str:
    """Format key performance metrics into a clean, monospace KPI strip.
    
    Example:
    ```text
    Net Worth: $42,500.25 | Cash: $34,850.00 | Burn (30d): $3,450.00
    ```
    """
    if not metrics:
        return ""
    segments = [f"{label}: {val}" for label, val in metrics]
    content = "  •  ".join(segments)
    return f"```text\n{content}\n```"


def format_ascii_table(
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[int] | None = None,
    right_align: list[bool] | None = None,
) -> str:
    """Render a perfectly aligned ASCII monospace table for Telegram.
    
    Prevents Telegram entity parsing errors caused by markdown pipe tables.
    """
    if not headers or not rows:
        return ""

    num_cols = len(headers)
    if col_widths is None:
        widths = [len(h) for h in headers]
        for row in rows:
            for i in range(min(num_cols, len(row))):
                widths[i] = max(widths[i], len(str(row[i])))
        col_widths = [w + 2 for w in widths]

    if right_align is None:
        right_align = [False] * num_cols

    # Header line
    hdr_parts = []
    for i, h in enumerate(headers):
        w = col_widths[i]
        hdr_parts.append(f"{h:>{w}}" if right_align[i] else f"{h:<{w}}")
    header_str = " ".join(hdr_parts)

    total_len = len(header_str)
    sep_str = "─" * total_len

    lines = ["```text", header_str, sep_str]

    for row in rows:
        row_parts = []
        for i in range(num_cols):
            val = str(row[i]) if i < len(row) else ""
            w = col_widths[i]
            row_parts.append(f"{val:>{w}}" if right_align[i] else f"{val:<{w}}")
        lines.append(" ".join(row_parts))

    lines.append("```")
    return "\n".join(lines)


def format_financial_accounts(accounts: list) -> str:
    """Format account balances into an executive monospace table."""
    headers = ["Account", "Mask", "Balance"]
    rows = []
    total = 0.0

    for a in accounts:
        sign = "$" if a.balance >= 0 else "-$"
        val_str = f"{sign}{abs(a.balance):,.2f}"
        name = (a.name[:16] + "…") if len(a.name) > 16 else a.name
        mask = a.mask or "••••"
        rows.append([name, mask, val_str])
        total += a.balance

    tot_sign = "$" if total >= 0 else "-$"
    rows.append(["Total Net Worth", "─", f"{tot_sign}{abs(total):,.2f}"])

    return format_ascii_table(
        headers=headers,
        rows=rows,
        col_widths=[18, 6, 14],
        right_align=[False, False, True],
    )


def format_transactions_card(transactions: list, limit: int = 5) -> str:
    """Format recent expenditures into a structured card."""
    if not transactions:
        return "_No recent transactions recorded._"

    lines = ["```text"]
    lines.append(f"{'Date':<7} {'Merchant':<18} {'Amount':>10}")
    lines.append("─" * 37)
    for t in transactions[:limit]:
        date_str = t.timestamp.strftime("%b %d")
        name = (t.merchant[:17] + "…") if len(t.merchant) > 17 else t.merchant
        amt_str = f"${t.amount:,.2f}"
        lines.append(f"{date_str:<7} {name:<18} {amt_str:>10}")
    lines.append("```")
    return "\n".join(lines)


def format_obligations_table(obligations: list[dict[str, Any]]) -> str:
    """Format upcoming recurring bills, car loans, and credit card obligations into a monospace schedule."""
    if not obligations:
        return "_No upcoming payment obligations scheduled._"

    headers = ["Due Date", "Obligation", "Amount", "Category"]
    rows = []
    for ob in obligations:
        due = str(ob.get("next_due_date") or "Scheduled")
        if len(due) == 10 and "-" in due:
            try:
                parts = due.split("-")
                month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                due = f"{month_names[int(parts[1])]} {int(parts[2]):02d}"
            except Exception:
                pass
        name = str(ob.get("name") or "Bill")
        if len(name) > 22:
            name = name[:21] + "…"
        amt = float(ob.get("amount") or 0.0)
        sign = "+" if ob.get("is_income") else ""
        amt_str = f"{sign}${amt:,.2f}"
        cat = str(ob.get("category") or "general").replace("_", " ").title()
        rows.append([due, name, amt_str, cat])

    return format_ascii_table(
        headers=headers,
        rows=rows,
        col_widths=[10, 24, 12, 14],
        right_align=[False, False, True, False],
    )


def format_insights_block(insights: list[str], title: str = "Executive Takeaways") -> str:
    """Render bulleted strategic insights and recommended next steps."""
    if not insights:
        return ""
    lines = [f"💡 **{title}**:"]
    for item in insights:
        clean = item.strip().lstrip("•- ")
        lines.append(f"• {clean}")
    return "\n".join(lines)


def format_alert_card(
    source: str,
    category: str,
    urgency: str,
    summary: str,
    details: str | None = None,
) -> str:
    """Format a proactive life-stream notification with urgency indicators."""
    urgency_upper = urgency.upper()
    icon = "🚨" if urgency_upper == "HIGH" else ("⚠️" if urgency_upper == "MEDIUM" else "🔹")

    lines = [
        f"🎩 {icon} **[ALERT] {source.upper()} • {category.capitalize()}**",
        DIVIDER_LINE,
        f"📌 **Urgency**: `{urgency_upper}`",
        f"📝 **Summary**: {summary}",
    ]
    if details:
        lines.append(f"\n{details}")
    lines.append(f"\n{DIVIDER_LINE}")
    return "\n".join(lines)


def format_footer(
    model_name: str | None = None,
    tokens: int | None = None,
    cost: float | None = None,
) -> str:
    """Format a discreet metadata footer."""
    parts = []
    if model_name:
        parts.append(f"Model: `{model_name}`")
    if tokens:
        parts.append(f"Tokens: {tokens:,}")
    if cost is not None:
        parts.append(f"Est: ${cost:.4f}")

    if not parts:
        return f"\n_{DIVIDER_LINE}\n🎩 LifeStream Assistant Online_"
    return f"\n_{' • '.join(parts)}_"


def format_executive_response(
    title: str,
    summary: str,
    body: str | None = None,
    insights: list[str] | None = None,
    metrics: list[tuple[str, str]] | None = None,
    badge: str = "REPORT",
    style: str | UXStylePreset = "executive",
    model_name: str | None = None,
    tokens: int | None = None,
    cost: float | None = None,
) -> str:
    """Assemble a complete, immaculate Telegram response adhering to the active UX style."""
    cfg = get_style_config(style)

    sections = [
        format_header(title=title, badge=badge, emoji=cfg.emoji),
        f"📌 **Summary**: {summary}",
    ]

    if metrics:
        sections.append(format_kpi_bar(metrics))

    if body:
        sections.append(body.strip())

    if cfg.include_insights and insights:
        sections.append(format_insights_block(insights))

    if cfg.include_metadata_footer and (model_name or tokens or cost):
        sections.append(format_footer(model_name=model_name, tokens=tokens, cost=cost))

    return "\n\n".join(sections)
