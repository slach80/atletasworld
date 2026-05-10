#!/usr/bin/env python3
"""
Test owner coaches page formatting and visibility.
"""
import asyncio
from playwright.async_api import async_playwright

SITE_URL = "https://atletasperformancecenter.com"

async def test_coaches_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        print("🧪 Testing Owner Coaches Page\n")

        # Open login
        await page.goto(f"{SITE_URL}/accounts/login/")
        print("1️⃣ Login page opened - please log in as owner...")

        # Wait for user to login
        await page.wait_for_url("**/owner-portal/**", timeout=120000)
        print("   ✓ Logged in\n")

        # Navigate to coaches page
        print("2️⃣ Navigating to coaches page...")
        await page.goto(f"{SITE_URL}/owner-portal/coaches/")
        await page.wait_for_load_state("networkidle")

        # Take full page screenshot
        await page.screenshot(path="/tmp/owner_coaches_full.png", full_page=True)
        print("   📸 Full page screenshot: /tmp/owner_coaches_full.png")

        # Check for table
        table = await page.query_selector("table")
        if table:
            print("   ✓ Table found")
        else:
            print("   ❌ Table NOT found")

        # Check for referral code column header
        ref_header = await page.query_selector("th:has-text('Referral Code')")
        if ref_header:
            print("   ✓ 'Referral Code' column header found")
        else:
            print("   ❌ 'Referral Code' column header NOT found")

        # Check for deactivate button
        deactivate_btn = await page.query_selector("button:has-text('Deactivate')")
        if deactivate_btn:
            print("   ✓ 'Deactivate' button found")
            # Check if it's visible
            is_visible = await deactivate_btn.is_visible()
            if is_visible:
                print("   ✓ Button is visible")
                # Get bounding box to check if it's cut off
                box = await deactivate_btn.bounding_box()
                if box:
                    print(f"   📏 Button position: x={box['x']}, y={box['y']}, width={box['width']}, height={box['height']}")
            else:
                print("   ⚠️  Button exists but not visible")
        else:
            print("   ⚠️  'Deactivate' button not found")

        # Check for referral codes in cells
        code_cells = await page.query_selector_all("code.font-mono")
        if code_cells:
            print(f"   ✓ Found {len(code_cells)} referral code badges")
        else:
            print("   ❌ No referral code badges found")

        # Check table width
        if table:
            table_box = await table.bounding_box()
            if table_box:
                viewport_width = 1920
                print(f"   📏 Table width: {table_box['width']}px (viewport: {viewport_width}px)")
                if table_box['width'] > viewport_width:
                    print(f"   ⚠️  Table is wider than viewport - content may be cut off!")

        print("\n✅ Test complete")
        print("Browser staying open for 30 seconds...")
        await page.wait_for_timeout(30000)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_coaches_page())
