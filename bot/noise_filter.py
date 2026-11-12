"""Hard-coded heuristic noise filter dropping routine non-actionable emails & notifications."""

import re
from typing import Any

# Standard shipping milestones that require ZERO action
ROUTINE_SHIPPING_PATTERNS = [
    r"\bshipped\b",
    r"\bout for delivery\b",
    r"\bdelivered\b",
    r"\bin transit\b",
    r"\barriving by\b",
    r"\barriving tomorrow\b",
    r"\barriving today\b",
    r"\bon its way\b",
    r"\bpackage received\b",
    r"\border confirmed\b",
    r"\byour amazon order\b",
    r"\btracking number\b",
    r"\bhas shipped\b",
]

# Exceptions that turn a shipping event into an actionable anomaly
SHIPPING_ANOMALY_PATTERNS = [
    r"\bdelay\b",
    r"\bdelayed\b",
    r"\blost\b",
    r"\bdamaged\b",
    r"\breturn\b",
    r"\brefund\b",
    r"\bexception\b",
    r"\baction required\b",
    r"\bundeliverable\b",
    r"\bfailed delivery\b",
    r"\breschedule\b",
]

# Routine bank statement notifications (actual bills are tracked via StatementExtractor)
ROUTINE_STATEMENT_PATTERNS = [
    r"\byour statement is now ready\b",
    r"\byour statement is ready\b",
    r"\bnew statement is ready\b",
    r"\byour new statement is now ready\b",
    r"\bebill is ready\b",
    r"\bmonthly statement is ready\b",
    r"\bview your monthly statement\b",
    r"\bview your statement online\b",
    r"\bopen to see your monthly statement\b",
]

# Exceptions that turn a statement email into an urgent alert
STATEMENT_ANOMALY_PATTERNS = [
    r"\bpast due\b",
    r"\boverdue\b",
    r"\blate fee\b",
    r"\bpayment declined\b",
    r"\bpayment failed\b",
    r"\bfailed\b",
    r"\bdeclined\b",
    r"\breturned payment\b",
    r"\baction required\b",
    r"\burgent\b",
    r"\binterest charge\b",
    r"\bunauthorized\b",
    r"\bsuspicious\b",
    r"\bminimum payment increased\b",
]

# Marketing, promotions, surveys, loyalty programs
MARKETING_PATTERNS = [
    r"\b\d+%\s*off\b",
    r"\bsave up to\b",
    r"\bdaily pick\b",
    r"\bexclusive offer\b",
    r"\bhot deal\b",
    r"\bloyalty rewards\b",
    r"\bplatinum loyalty\b",
    r"\bearn cash back\b",
    r"\bactivate offers?\b",
    r"\bsurvey\b",
    r"\bfeedback\b",
    r"\bexplore a high yield\b",
    r"\bmust reads\b",
    r"\bturn back your clock\b",
    r"\bdaylight saving\b",
    r"\bdownload the (new )?mobile app\b",
    r"\bfind comfort in bundling\b",
    r"\bthanks for trying snapshot\b",
    r"\bterms of (service|use) update\b",
    r"\bprivacy policy update\b",
    r"\bapply for an unsecured loan\b",
]


def is_hardcoded_noise(
    source: str,
    title: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Check if an incoming life-stream event should be dropped immediately without waking any LLM.

    Returns:
        (is_noise: bool, reason: str)
    """
    combined = f"{title} {summary}".lower()

    # 1. Check marketing / promotional newsletters
    for pat in MARKETING_PATTERNS:
        if re.search(pat, combined):
            return True, f"marketing_pattern_matched: {pat}"

    # 2. Check routine shipping milestones
    is_shipping = any(re.search(pat, combined) for pat in ROUTINE_SHIPPING_PATTERNS)
    if is_shipping:
        has_anomaly = any(re.search(pat, combined) for pat in SHIPPING_ANOMALY_PATTERNS)
        if not has_anomaly:
            return True, "routine_shipping_update_without_anomaly"

    # 3. Check routine statement availability
    is_statement = any(re.search(pat, combined) for pat in ROUTINE_STATEMENT_PATTERNS)
    if is_statement:
        has_statement_anomaly = any(re.search(pat, combined) for pat in STATEMENT_ANOMALY_PATTERNS)
        if not has_statement_anomaly:
            return True, "routine_statement_notice_without_anomaly"

    return False, ""
