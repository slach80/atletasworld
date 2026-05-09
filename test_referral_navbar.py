#!/usr/bin/env python3
"""
Quick test to check navbar on referral page.
"""
import asyncio
from playwright.async_api import async_playwright

SITE_URL = "https://atletasperformancecenter.com"

async def test_navbar():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("🧪 Testing Referral Page Navbar\n")

        # Open login
        await page.goto(f"{SITE_URL}/accounts/login/")
        print("1️⃣ Login page opened - please log in...")

        # Wait for user to login
        await page.wait_for_url("**/portal/**", timeout=120000)
        print("   ✓ Logged in\n")

        # Go to referral page
        print("2️⃣ Navigating to referral page...")
        await page.goto(f"{SITE_URL}/portal/referral/")
        await page.wait_for_load_state("networkidle")

        # Take screenshot
        await page.screenshot(path="/tmp/referral_with_nav_check.png", full_page=True)
        print("   📸 Screenshot: /tmp/referral_with_nav_check.png")

        # Check for navbar elements
        print("\n3️⃣ Checking navbar elements...")

        nav = await page.query_selector("nav")
        if nav:
            print("   ✓ <nav> element found")
        else:
            print("   ❌ <nav> element NOT found")

        dashboard_link = await page.query_selector('a[href*="dashboard"]')
        if dashboard_link:
            print("   ✓ Dashboard link found")
        else:
            print("   ❌ Dashboard link NOT found")

        logo = await page.query_selector('img[alt*="Atletas"]')
        if logo:
            print("   ✓ Logo found")
        else:
            print("   ❌ Logo NOT found")

        book_btn = await page.query_selector('a:has-text("Book Session")')
        if book_btn:
            print("   ✓ 'Book Session' button found")
        else:
            print("   ❌ 'Book Session' button NOT found")

        print("\n✅ Test complete - check screenshot")
        print("Browser will stay open for 30 seconds...")
        await page.wait_for_timeout(30000)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_navbar())
