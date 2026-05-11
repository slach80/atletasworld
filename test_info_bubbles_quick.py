#!/usr/bin/env python3
"""
Quick test to verify info bubbles are now visible after deployment.
"""
import asyncio
from playwright.async_api import async_playwright

SITE_URL = "https://atletasperformancecenter.com"

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        print("Opening notifications page...")
        await page.goto(f"{SITE_URL}/accounts/login/")

        # Wait for login
        await page.wait_for_url("**/owner-portal/**", timeout=120000)

        # Go to notifications
        await page.goto(f"{SITE_URL}/owner-portal/notifications/")
        await page.wait_for_load_state("networkidle")

        # Force reload to clear cache
        await page.reload()
        await page.wait_for_load_state("networkidle")

        print("\nSearching for info icons...")

        # Look for the info emoji in the page content
        content = await page.content()
        emoji_count = content.count("ℹ️")
        print(f"Found {emoji_count} ℹ️ emojis in HTML source")

        # Try to find visible spans with the emoji
        info_spans = await page.query_selector_all("span:has-text('ℹ️')")
        print(f"Found {len(info_spans)} visible info icon spans")

        if len(info_spans) > 0:
            print("\n✅ Info icons are present!")

            # Test hover on first one
            first_span = info_spans[0]
            parent_label = await first_span.evaluate_handle("el => el.closest('label')")

            print("\nTesting hover on first info icon...")
            await parent_label.as_element().hover()
            await page.wait_for_timeout(500)

            # Take screenshot
            await page.screenshot(path="/tmp/info_bubbles_working.png")
            print("Screenshot saved: /tmp/info_bubbles_working.png")

            # Check if tooltip is visible
            tooltip = await page.query_selector("div.bg-gray-900.text-white")
            if tooltip:
                is_visible = await tooltip.is_visible()
                print(f"\nTooltip visible: {is_visible}")
                if is_visible:
                    text = await tooltip.inner_text()
                    print(f"Tooltip text: {text}")
        else:
            print("\n❌ Info icons still not visible")
            await page.screenshot(path="/tmp/info_bubbles_missing.png")
            print("Screenshot saved: /tmp/info_bubbles_missing.png")

        print("\nKeeping browser open for 20 seconds...")
        await page.wait_for_timeout(20000)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
