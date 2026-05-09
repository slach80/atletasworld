#!/usr/bin/env python3
"""
Manual Playwright test - opens browser for user to login and navigate.
Tests referral program with human interaction.
"""
import asyncio
from playwright.async_api import async_playwright

SITE_URL = "https://atletasperformancecenter.com"

async def test_manual():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("🧪 Manual Referral Program Test")
        print("=" * 50)
        print("\n📖 Browser opening - please log in when ready...")

        # Open login page
        print("\n1️⃣ Opening login page...")
        await page.goto(f"{SITE_URL}/accounts/login/")
        await page.wait_for_load_state("networkidle")

        print("2️⃣ Please log in...")
        print("   Waiting for navigation to portal...")

        # Wait for user to login (max 60 seconds)
        try:
            await page.wait_for_url("**/portal/**", timeout=60000)
            print("   ✓ Login successful!")
        except:
            print("   ⚠️  Login timeout or redirected elsewhere")

        # Give user a moment
        await page.wait_for_timeout(2000)

        # Test client portal pages
        print("\n3️⃣ Testing client portal pages...")
        test_pages = [
            ("/portal/dashboard/", "Dashboard"),
            ("/portal/players/", "Players"),
            ("/portal/bookings/", "Bookings"),
            ("/portal/packages/", "Packages"),
            ("/portal/profile/", "Profile"),
            ("/portal/referral/", "Referral Program"),
        ]

        for url, name in test_pages:
            print(f"\n   📄 Testing: {name}")
            await page.goto(f"{SITE_URL}{url}")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1000)

            # Check for errors
            has_error = await page.query_selector("text=Server Error")
            if has_error:
                print(f"      ❌ Server Error (500) on {name}!")
                await page.screenshot(path=f"/tmp/{name.lower().replace(' ', '_')}_error.png")
            else:
                print(f"      ✓ {name} loaded successfully")

            # Check for referral link in nav
            if url != "/portal/referral/":
                referral_link = await page.query_selector('a[href*="referral"]')
                if referral_link:
                    print(f"      ✓ Referral link found in navigation")
                else:
                    print(f"      ⚠️  Referral link not found in navigation")

            # Take screenshot
            screenshot_path = f"/tmp/{name.lower().replace(' ', '_')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"      📸 Screenshot: {screenshot_path}")

        # Special checks for referral page
        print("\n4️⃣ Detailed referral page checks...")
        await page.goto(f"{SITE_URL}/portal/referral/")
        await page.wait_for_load_state("networkidle")

        elements_to_check = [
            ("text=Your Referral Code", "Referral Code section"),
            ("text=Share Link", "Share Link section"),
            ("text=Total Referrals", "Stats section"),
            ("text=Referrals Given", "Referrals history"),
        ]

        for selector, description in elements_to_check:
            element = await page.query_selector(selector)
            if element:
                print(f"   ✓ {description} present")
            else:
                print(f"   ⚠️  {description} missing")

        print("\n✅ Test complete!")
        print("\nScreenshots saved to /tmp/")
        print("\nBrowser staying open for 60 seconds...")
        await page.wait_for_timeout(60000)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_manual())
