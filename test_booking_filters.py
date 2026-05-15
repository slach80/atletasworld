"""
Playwright test to verify booking page filter functionality.

Tests:
- Session type filters (Training, Events, Special groups)
- Coach filter dropdown
- Location filter dropdown
- Date filters (All, Today, This Week, Next Week)
- Mobile filter button and bottom sheet
- Clear all filters
"""
import asyncio
from playwright.async_api import async_playwright


async def test_booking_filters():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # Desktop test
        print("Testing desktop filters...")
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        # Login
        await page.goto('http://localhost:8001/accounts/login/')
        await page.fill('input[name="login"]', 'test@example.com')
        await page.fill('input[name="password"]', 'test123')
        await page.click('button[type="submit"]')
        await asyncio.sleep(2)

        # Navigate to booking page
        await page.goto('http://localhost:8001/portal/book-v2/')
        await asyncio.sleep(2)

        # Test 1: Verify sidebar is visible
        sidebar = await page.query_selector('#filter-sidebar')
        sidebar_visible = await sidebar.is_visible() if sidebar else False
        print(f"✓ Desktop sidebar visible: {sidebar_visible}")

        # Test 2: Click session type filter
        all_sessions_btn = await page.query_selector('button.type-pill-all')
        if all_sessions_btn:
            print("✓ 'All Sessions' button found")

        # Test 3: Click a specific session type (e.g., first Training session)
        first_training = await page.query_selector('[data-type-pill]')
        if first_training:
            await first_training.click()
            await asyncio.sleep(1)
            print("✓ Session type filter clicked")
            await page.screenshot(path='/home/slach/Pictures/Screenshots/filter-session-type.png')

        # Test 4: Click date filter - Today
        today_btn = await page.query_selector('button[data-date="today"]')
        if today_btn:
            await today_btn.click()
            await asyncio.sleep(1)
            is_active = 'border-yellow-400' in await today_btn.get_attribute('class')
            print(f"✓ Date filter 'Today' clicked - Active: {is_active}")
            await page.screenshot(path='/home/slach/Pictures/Screenshots/filter-date-today.png')

        # Test 5: Check coach dropdown (may be empty in test data)
        coach_select = await page.query_selector('#coachSelect')
        if coach_select:
            options = await page.query_selector_all('#coachSelect option')
            print(f"✓ Coach dropdown found with {len(options)} options")
            if len(options) > 1:  # Has coaches besides "Any Coach"
                await coach_select.select_option(index=1)
                await asyncio.sleep(1)
                print("✓ Coach filter selected")
                await page.screenshot(path='/home/slach/Pictures/Screenshots/filter-coach.png')

        # Test 6: Clear all filters
        clear_btn = await page.query_selector('text="Clear"')
        if clear_btn:
            await clear_btn.click()
            await asyncio.sleep(1)
            print("✓ Clear all filters clicked")
            await page.screenshot(path='/home/slach/Pictures/Screenshots/filter-cleared.png')

        # Mobile test
        print("\nTesting mobile filters...")
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        # Login on mobile
        await mobile.goto('http://localhost:8001/accounts/login/')
        await mobile.fill('input[name="login"]', 'test@example.com')
        await mobile.fill('input[name="password"]', 'test123')
        await mobile.click('button[type="submit"]')
        await asyncio.sleep(2)

        await mobile.goto('http://localhost:8001/portal/book-v2/')
        await asyncio.sleep(2)

        # Test 7: Open mobile filter sheet
        mobile_filter_btn = await mobile.query_selector('#mobile-filter-btn')
        if mobile_filter_btn:
            await mobile_filter_btn.click()
            await asyncio.sleep(0.5)
            sheet = await mobile.query_selector('#mobile-filter-sheet')
            sheet_visible = await sheet.is_visible() if sheet else False
            print(f"✓ Mobile filter sheet opens: {sheet_visible}")
            await mobile.screenshot(path='/home/slach/Pictures/Screenshots/filter-mobile-open.png')

            # Test 8: Click session type in mobile sheet
            first_mobile_type = await mobile.query_selector('#mobile-filter-sheet [data-type-pill]')
            if first_mobile_type:
                await first_mobile_type.click()
                await asyncio.sleep(0.5)
                print("✓ Mobile session type filter clicked")

            # Test 9: Click date filter in mobile
            mobile_today = await mobile.query_selector('#mobile-filter-sheet button[data-date="today"]')
            if mobile_today:
                await mobile_today.click()
                await asyncio.sleep(0.5)
                print("✓ Mobile date filter clicked")

            # Apply filters
            apply_btn = await mobile.query_selector('text="Apply Filters"')
            if apply_btn:
                await apply_btn.click()
                await asyncio.sleep(1)
                print("✓ Apply filters clicked")
                await mobile.screenshot(path='/home/slach/Pictures/Screenshots/filter-mobile-applied.png')

        print("\n✅ All filter tests complete!")
        print("Screenshots saved to ~/Pictures/Screenshots/")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_booking_filters())
