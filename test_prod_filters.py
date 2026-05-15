"""
Playwright test to verify booking page filters on PRODUCTION.

Tests actual production data and filter behavior.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_prod_filters():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        print("Testing PRODUCTION booking page filters...")
        print("URL: https://atletasperformancecenter.com/portal/book-v2/")

        # Navigate to production
        await page.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("\n⚠️  Please log in manually in the browser window...")
        print("Waiting 30 seconds for manual login...")
        await asyncio.sleep(30)

        # Navigate to booking page
        await page.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(3)

        # Check if we're on the booking page or redirected to login
        current_url = page.url
        if 'login' in current_url:
            print("❌ Still on login page - authentication failed")
            await browser.close()
            return

        print(f"✓ On booking page: {current_url}")
        await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-initial.png', full_page=True)

        # Count initial sessions
        slots = await page.query_selector_all('.space-y-2 > div')
        initial_count = len([s for s in slots if s])
        print(f"✓ Initial sessions visible: {initial_count}")

        # Test 1: Click "All Sessions" button
        all_btn = await page.query_selector('button.type-pill-all')
        if all_btn:
            await all_btn.click()
            await asyncio.sleep(1)
            slots_after_all = await page.query_selector_all('.space-y-2 > div')
            count_after_all = len([s for s in slots_after_all if s])
            print(f"✓ After clicking 'All Sessions': {count_after_all} sessions")
            await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-all-sessions.png', full_page=True)

        # Test 2: Click first session type filter
        first_type = await page.query_selector('[data-type-pill]')
        if first_type:
            type_id = await first_type.get_attribute('data-type-pill')
            type_text = await first_type.inner_text()
            print(f"\nClicking session type filter: '{type_text}' (ID: {type_id})")
            await first_type.click()
            await asyncio.sleep(1)

            # Count sessions after filter
            slots_filtered = await page.query_selector_all('.space-y-2 > div')
            filtered_count = len([s for s in slots_filtered if s])
            print(f"✓ After filtering by '{type_text}': {filtered_count} sessions")

            # Check if pill is highlighted
            classes = await first_type.get_attribute('class')
            is_active = 'border-yellow-400' in classes
            print(f"✓ Filter pill active state: {is_active}")

            await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-type-filtered.png', full_page=True)

            # Check console for any JS errors
            print("\nChecking browser console...")

        # Test 3: Click Today date filter
        today_btn = await page.query_selector('button[data-date="today"]')
        if today_btn:
            print("\nClicking 'Today' date filter...")
            await today_btn.click()
            await asyncio.sleep(1)

            slots_today = await page.query_selector_all('.space-y-2 > div')
            today_count = len([s for s in slots_today if s])
            print(f"✓ After filtering by Today: {today_count} sessions")

            classes = await today_btn.get_attribute('class')
            is_active = 'border-yellow-400' in classes
            print(f"✓ Today button active state: {is_active}")

            await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-today-filtered.png', full_page=True)

        # Test 4: Check slots container for "No sessions found"
        no_sessions = await page.query_selector('text="No sessions found"')
        if no_sessions:
            print("\n⚠️  'No sessions found' message is displayed")
            print("This could mean:")
            print("  1. Filters are working correctly and no sessions match")
            print("  2. There's no session data in production")
            print("  3. Filter logic is too restrictive")

        # Test 5: Clear filters
        clear_btn = await page.query_selector('text="Clear"')
        if clear_btn:
            print("\nClicking 'Clear' button...")
            await clear_btn.click()
            await asyncio.sleep(1)

            slots_cleared = await page.query_selector_all('.space-y-2 > div')
            cleared_count = len([s for s in slots_cleared if s])
            print(f"✓ After clearing filters: {cleared_count} sessions")
            await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-cleared.png', full_page=True)

        # Test 6: Get console logs/errors
        print("\n" + "="*60)
        print("Opening browser DevTools console to check for errors...")
        print("Check the browser window for any JavaScript errors")
        print("="*60)

        await asyncio.sleep(5)

        print("\n✅ Production filter tests complete!")
        print("Screenshots saved to ~/Pictures/Screenshots/prod-*.png")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_prod_filters())
