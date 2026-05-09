#!/usr/bin/env python3
"""
Authenticated Playwright test for referral program.
Tests navigation consistency and referral page functionality.
"""
import asyncio
from playwright.async_api import async_playwright
import os

SITE_URL = "https://atletasperformancecenter.com"
# Set credentials via env vars: TEST_EMAIL and TEST_PASSWORD
EMAIL = os.getenv("TEST_EMAIL", "")
PASSWORD = os.getenv("TEST_PASSWORD", "")

async def test_with_auth():
    if not EMAIL or not PASSWORD:
        print("❌ Set TEST_EMAIL and TEST_PASSWORD env vars")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("🧪 Authenticated Referral Program Test\n")

        # Login
        print("1️⃣ Logging in...")
        await page.goto(f"{SITE_URL}/accounts/login/")
        await page.fill('input[name="login"]', EMAIL)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")
        print("   ✓ Logged in")

        # Test client portal pages for referral link
        print("\n2️⃣ Testing referral link in client portal navigation...")
        test_pages = [
            "/portal/dashboard/",
            "/portal/players/",
            "/portal/bookings/",
            "/portal/packages/",
            "/portal/profile/",
        ]

        for url in test_pages:
            await page.goto(f"{SITE_URL}{url}")
            await page.wait_for_load_state("networkidle")

            # Check desktop nav (Account dropdown)
            try:
                # Hover over Account dropdown
                account_btn = await page.query_selector('button:has-text("Account")')
                if account_btn:
                    await account_btn.hover()
                    await page.wait_for_timeout(500)  # Wait for dropdown
                    referral_link = await page.query_selector('a[href*="referral"]')
                    if referral_link:
                        print(f"   ✓ {url} - referral link found")
                    else:
                        print(f"   ❌ {url} - referral link missing in dropdown!")
                else:
                    print(f"   ⚠️  {url} - Account button not found")
            except Exception as e:
                print(f"   ❌ {url} - Error: {e}")

        # Test referral page itself
        print("\n3️⃣ Testing referral page...")
        await page.goto(f"{SITE_URL}/portal/referral/")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="/tmp/referral_authenticated.png")

        # Check key elements
        has_code = await page.query_selector("text=Your Referral Code")
        has_share = await page.query_selector("text=Share Link")
        has_stats = await page.query_selector("text=Total Referrals")

        if has_code:
            print("   ✓ 'Your Referral Code' section present")
        else:
            print("   ❌ 'Your Referral Code' missing")

        if has_share:
            print("   ✓ 'Share Link' section present")
        else:
            print("   ❌ 'Share Link' missing")

        if has_stats:
            print("   ✓ Stats section present")
        else:
            print("   ❌ Stats missing")

        print(f"\n   📸 Screenshot: /tmp/referral_authenticated.png")

        print("\n✅ Authenticated test complete!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_with_auth())
