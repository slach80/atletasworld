#!/usr/bin/env python3
"""
Test owner notifications page - verify info bubbles (tooltips) are visible.
"""
import asyncio
from playwright.async_api import async_playwright

SITE_URL = "https://atletasperformancecenter.com"

async def test_notifications_tooltips():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        print("🧪 Testing Owner Notifications Tooltips\n")

        # Open login
        await page.goto(f"{SITE_URL}/accounts/login/")
        print("1️⃣ Login page opened - please log in as owner...")

        # Wait for user to login
        await page.wait_for_url("**/owner-portal/**", timeout=120000)
        print("   ✓ Logged in\n")

        # Navigate to notifications page
        print("2️⃣ Navigating to notifications page...")
        await page.goto(f"{SITE_URL}/owner-portal/notifications/")
        await page.wait_for_load_state("networkidle")
        print("   ✓ Page loaded\n")

        # Check if base template navigation is present
        print("3️⃣ Checking navigation...")
        nav = await page.query_selector("nav.bg-primary")
        if nav:
            print("   ✓ Base template navigation found")

            # Check for dropdown menus
            people_dropdown = await page.query_selector("button:has-text('People')")
            operations_dropdown = await page.query_selector("button:has-text('Operations')")
            if people_dropdown and operations_dropdown:
                print("   ✓ Dropdown menus present")
            else:
                print("   ⚠️  Dropdown menus not found")
        else:
            print("   ❌ Navigation NOT using base template")

        print("\n4️⃣ Checking info bubbles (ℹ️ icons)...")

        # Find all info icons
        info_icons = await page.query_selector_all("span[title]:has-text('ℹ️')")
        print(f"   Found {len(info_icons)} info icons\n")

        if len(info_icons) == 0:
            print("   ❌ No info icons found!")
        else:
            # Test first few tooltips
            test_options = [
                ("All Clients", "All registered client accounts"),
                ("All Coaches", "active coach accounts"),
                ("Active Clients", "last 30 days"),
            ]

            for option_name, expected_text in test_options:
                print(f"   Testing tooltip: {option_name}")

                # Find the label containing this option
                label = await page.query_selector(f"label:has-text('{option_name}')")
                if not label:
                    print(f"      ❌ Label for '{option_name}' not found")
                    continue

                # Find the info icon within this label
                icon = await label.query_selector("span[title]")
                if not icon:
                    print(f"      ❌ Info icon not found in label")
                    continue

                # Check if tooltip div exists
                tooltip = await label.query_selector("div.absolute.bg-gray-900")
                if not tooltip:
                    print(f"      ❌ Tooltip div not found")
                    continue

                # Check initial state (should be hidden)
                is_hidden_before = await tooltip.evaluate("el => el.classList.contains('hidden')")
                print(f"      Tooltip hidden before hover: {is_hidden_before}")

                # Hover over the label
                await label.hover()
                await page.wait_for_timeout(300)  # Wait for transition

                # Check if tooltip became visible
                is_visible = await tooltip.is_visible()
                tooltip_text = await tooltip.inner_text()

                if is_visible:
                    print(f"      ✓ Tooltip visible on hover")
                    print(f"      ✓ Text: {tooltip_text[:50]}...")
                    if expected_text.lower() in tooltip_text.lower():
                        print(f"      ✓ Contains expected text")
                    else:
                        print(f"      ⚠️  Expected text not found: '{expected_text}'")
                else:
                    print(f"      ❌ Tooltip NOT visible on hover")
                    print(f"      Classes: {await tooltip.get_attribute('class')}")

                # Move mouse away
                await page.mouse.move(0, 0)
                await page.wait_for_timeout(200)
                print()

        # Take screenshot
        await page.screenshot(path="/tmp/notifications_tooltips.png", full_page=True)
        print("📸 Screenshot saved: /tmp/notifications_tooltips.png\n")

        # Take screenshot while hovering over first option
        print("5️⃣ Taking screenshot with tooltip visible...")
        first_label = await page.query_selector("label:has-text('All Clients')")
        if first_label:
            await first_label.hover()
            await page.wait_for_timeout(500)
            await page.screenshot(path="/tmp/notifications_tooltip_hover.png")
            print("   📸 Hover screenshot: /tmp/notifications_tooltip_hover.png\n")

        print("✅ Test complete")
        print("Browser staying open for 30 seconds...")
        await page.wait_for_timeout(30000)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_notifications_tooltips())
