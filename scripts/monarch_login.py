"""Interactive CLI to authenticate with Monarch Money and save the session token to .env."""

import asyncio
import os
import sys
from dotenv import set_key
from monarchmoney import MonarchMoney


async def main() -> None:
    print("=" * 65)
    print("🔐 Monarch Money Interactive Authentication")
    print("=" * 65)
    print("This will log you into Monarch Money securely and save the session token")
    print("to your .env file so your Personal AI Assistant can access your accounts.")
    print("Your password is not saved — only the authenticated session token.\n")

    mm = MonarchMoney()
    try:
        await mm.interactive_login()
    except Exception as exc:
        print(f"\n❌ Login failed: {exc}")
        return

    token = mm.token
    if not token:
        print("\n❌ Could not retrieve session token.")
        return

    env_path = os.path.abspath(".env")
    set_key(env_path, "MONARCH_TOKEN", token)
    print("\n" + "=" * 65)
    print("✅ Successfully authenticated with Monarch Money!")
    print(f"✅ MONARCH_TOKEN saved to {env_path}")
    print("=" * 65)

    # Test fetching accounts
    try:
        print("\nVerifying connected accounts...")
        accounts_data = await mm.get_accounts()
        accounts = accounts_data.get("accounts", [])
        print(f"Found {len(accounts)} connected account(s):")
        for acc in accounts:
            name = acc.get("displayName", "Account")
            mask = acc.get("mask") or "****"
            bal = acc.get("currentBalance", 0.0)
            sign = "$" if bal >= 0 else "-$"
            print(f"  • {name} ({mask}): {sign}{abs(bal):,.2f}")
        print("\n🎉 Live setup complete! Your Assistant will now pull your real finances.")
    except Exception as err:
        print(f"Note: Token saved, but error fetching initial summary: {err}")


if __name__ == "__main__":
    asyncio.run(main())
