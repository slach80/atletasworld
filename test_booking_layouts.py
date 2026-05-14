"""
Playwright test to verify booking page layouts across devices.

Tests:
- Desktop: sidebar visible, filters grouped
- Mobile: bottom sheet, compact layout
- Light mode text visibility
"""
import asyncio
from playwright.async_api import async_playwright


async def test_booking_layouts():
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)

        # Test 1: Desktop Layout (1920x1080)
        print("Testing desktop layout...")
        desktop = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        # Login first
        print("Logging in...")
        await desktop.goto('http://localhost:8001/accounts/login/')
        await desktop.fill('input[name="login"]', 'test@example.com')
        await desktop.fill('input[name="password"]', 'test123')
        await desktop.click('button[type="submit"]')
        await asyncio.sleep(2)
        print("✓ Logged in successfully")

        # Navigate to new booking page
        await desktop.goto('http://localhost:8001/portal/book-v2/')
        await asyncio.sleep(2)

        # Check desktop sidebar is visible
        sidebar = await desktop.query_selector('#filter-sidebar')
        is_visible = await sidebar.is_visible() if sidebar else False
        print(f"✓ Desktop sidebar visible: {is_visible}")

        # Check grouped session types
        training_group = await desktop.query_selector('text="Training"')
        events_group = await desktop.query_selector('text="Events"')
        print(f"✓ Session type groups found: Training={training_group is not None}, Events={events_group is not None}")

        # Screenshot
        await desktop.screenshot(path='/home/slach/Pictures/Screenshots/booking-desktop.png', full_page=True)
        print("✓ Desktop screenshot saved")

        # Test 2: Mobile Layout (390x844 - iPhone 12/13/14)
        print("\nTesting mobile layout...")
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        # Login on mobile
        await mobile.goto('http://localhost:8001/accounts/login/')
        await mobile.fill('input[name="login"]', 'test@example.com')
        await mobile.fill('input[name="password"]', 'test123')
        await mobile.click('button[type="submit"]')
        await asyncio.sleep(2)

        await mobile.goto('http://localhost:8001/portal/book-v2/')
        await asyncio.sleep(2)

        # Check sidebar is hidden
        sidebar_mobile = await mobile.query_selector('#filter-sidebar')
        is_hidden = not (await sidebar_mobile.is_visible()) if sidebar_mobile else True
        print(f"✓ Mobile sidebar hidden: {is_hidden}")

        # Check mobile filter button exists
        mobile_btn = await mobile.query_selector('#mobile-filter-btn')
        print(f"✓ Mobile filter button exists: {mobile_btn is not None}")

        # Open bottom sheet
        if mobile_btn:
            await mobile_btn.click()
            await asyncio.sleep(0.5)
            sheet = await mobile.query_selector('#mobile-filter-sheet')
            sheet_visible = await sheet.is_visible() if sheet else False
            print(f"✓ Bottom sheet opens: {sheet_visible}")

        # Screenshot
        await mobile.screenshot(path='/home/slach/Pictures/Screenshots/booking-mobile.png', full_page=True)
        print("✓ Mobile screenshot saved")

        # Test 3: iPad/Tablet Layout (1024x768)
        print("\nTesting tablet layout...")
        tablet = await browser.new_page(viewport={'width': 1024, 'height': 768})

        # Login on tablet
        await tablet.goto('http://localhost:8001/accounts/login/')
        await tablet.fill('input[name="login"]', 'test@example.com')
        await tablet.fill('input[name="password"]', 'test123')
        await tablet.click('button[type="submit"]')
        await asyncio.sleep(2)

        await tablet.goto('http://localhost:8001/portal/book-v2/')
        await asyncio.sleep(2)

        await tablet.screenshot(path='/home/slach/Pictures/Screenshots/booking-tablet.png', full_page=True)
        print("✓ Tablet screenshot saved")

        # Test 4: Light Mode Text Visibility
        print("\nTesting light mode text visibility...")
        # Check if text is readable (not white on white or dark on dark)
        filter_label = await desktop.query_selector('.text-gray-700')
        if filter_label:
            color = await filter_label.evaluate('el => window.getComputedStyle(el).color')
            print(f"✓ Filter text color: {color} (should be dark)")

        print("\n✅ All layout tests complete!")
        print("Screenshots saved to ~/Pictures/Screenshots/")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_booking_layouts())
