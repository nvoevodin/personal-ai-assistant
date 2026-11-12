"""Test hard-coded noise filter rules."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.noise_filter import is_hardcoded_noise


def main() -> None:
    test_cases = [
        # (title, summary, expected_noise)
        ("SiriusXM", "Hot deal for your Hyundai IONIQ 5! Enjoy 3 months for $1", True),
        ("Guitar Center Daily Pick", "Daily Pick: Save 15% on Epiphone Les Paul", True),
        ("Progressive", "Platinum loyalty rewards are coming your way.", True),
        ("Frontier Airlines Mastercard", "Your new statement is now ready", True),
        ("Amazon Delivery", "Your package has shipped and is on its way", True),
        ("Amazon Delivery", "Your package was delivered at front door", True),
        ("Hyundai Motor America", "Nikita, Turn Back Your Clock 1 Hour For Standard Time", True),
        ("Hyundai Motor Finance", "Nikita, download the new mobile app now", True),
        ("UPS Shipping", "Delivery delayed due to severe weather conditions", False),
        ("Barclays Alert", "Your automatic payment failed or was declined", False),
        ("Chase Security", "New sign-in from unrecognized location", False),
        ("Monarch Transaction", "Large unexpected charge of $1,450 at unknown merchant", False),
    ]

    for title, summary, expected in test_cases:
        is_noise, reason = is_hardcoded_noise("test", title, summary)
        print(f"[{'NOISE' if is_noise else 'KEEP':<5}] (Expected: {'NOISE' if expected else 'KEEP'}) -> '{title}': '{summary[:40]}...' Reason: {reason}")
        assert is_noise == expected, f"Failed for {title}: expected {expected}, got {is_noise}"

    print("\n[SUCCESS] All noise filter assertions passed!")


if __name__ == "__main__":
    main()
