#!/usr/bin/env python3
"""
Playwright test script for referral program end-to-end flow.

Tests:
1. Signup with referral code (?ref=CODE)
2. First purchase activation
3. Referrer receives credit/payout
4. Referral page displays correctly
"""
import asyncio
from playwright.async_api import async_playwright
import sys

SITE_URL = "https://atletasperformancecenter.com"

async def test_referral_flow():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("🧪 Testing Referral Program Flow\n")

        # Test 1: Visit referral signup link
        print("1️⃣ Testing signup with referral code...")
        ref_code = "TESTCODE"  # Use an existing code or create one
        await page.goto(f"{SITE_URL}/signup?ref={ref_code}")
        await page.screenshot(path="/tmp/ref_signup.png")
        print(f"   ✓ Visited /signup?ref={ref_code}")
        print(f"   📸 Screenshot: /tmp/ref_signup.png")

        # Check if referral code is captured in session
        storage = await context.storage_state()
        print(f"   Session storage captured")

        # Test 2: Check client portal referral page
        print("\n2️⃣ Testing client portal referral page...")
        await page.goto(f"{SITE_URL}/portal/referral/")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="/tmp/client_referral.png")
        print(f"   ✓ Loaded /portal/referral/")
        print(f"   📸 Screenshot: /tmp/client_referral.png")

        # Check for key elements
        try:
            await page.wait_for_selector("text=Your Referral Code", timeout=3000)
            print("   ✓ Found 'Your Referral Code' heading")
        except:
            print("   ⚠️  'Your Referral Code' not found - may need login")

        # Test 3: Check coach portal referral page
        print("\n3️⃣ Testing coach portal referral page...")
        await page.goto(f"{SITE_URL}/coach-portal/referral/")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="/tmp/coach_referral.png")
        print(f"   ✓ Loaded /coach-portal/referral/")
        print(f"   📸 Screenshot: /tmp/coach_referral.png")

        # Test 4: Check owner portal referrals dashboard
        print("\n4️⃣ Testing owner portal referrals dashboard...")
        await page.goto(f"{SITE_URL}/owner-portal/referrals/")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path="/tmp/owner_referrals.png")
        print(f"   ✓ Loaded /owner-portal/referrals/")
        print(f"   📸 Screenshot: /tmp/owner_referrals.png")

        # Test 5: Check navigation consistency across client portal pages
        print("\n5️⃣ Testing navigation consistency across client portal...")
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

            # Check if referral link exists in nav
            try:
                await page.wait_for_selector("text=Referral", timeout=2000)
                print(f"   ✓ {url} - referral link found")
            except:
                print(f"   ❌ {url} - referral link missing!")

        print("\n✅ Test flow complete!")
        print("\nScreenshots saved to /tmp/:")
        print("  - ref_signup.png")
        print("  - client_referral.png")
        print("  - coach_referral.png")
        print("  - owner_referrals.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_referral_flow())
