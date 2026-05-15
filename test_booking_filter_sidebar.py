"""
Test booking filter sidebar on production - check for cutoff and missing elements.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_booking_filter_sidebar():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        print("Testing booking filter sidebar on production...")
        await page.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await page.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(3)

        print("\n=== Checking Filter Sidebar ===")

        # Check if sidebar is visible
        sidebar = await page.query_selector('#filter-sidebar')
        if sidebar:
            is_visible = await sidebar.is_visible()
            print(f"✓ Sidebar visible: {is_visible}")

            # Get sidebar dimensions and scroll info
            sidebar_info = await sidebar.evaluate('''(el) => {
                return {
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    scrollTop: el.scrollTop,
                    hasOverflow: el.scrollHeight > el.clientHeight
                };
            }''')

            print(f"\nSidebar Dimensions:")
            print(f"  Content height: {sidebar_info['scrollHeight']}px")
            print(f"  Visible height: {sidebar_info['clientHeight']}px")
            print(f"  Scroll position: {sidebar_info['scrollTop']}px")
            print(f"  Has overflow: {sidebar_info['hasOverflow']}")

            # Check for Players section
            players_section = await page.query_selector('#filter-sidebar label:text("Players")')
            if players_section:
                print("\n✓ Players section found")

                # Check for player checkboxes
                player_checkboxes = await page.query_selector_all('#playerCheckboxes input[type="checkbox"]')
                print(f"✓ Player checkboxes found: {len(player_checkboxes)}")

                # Get player names
                player_labels = await page.query_selector_all('#playerCheckboxes label')
                for i, label in enumerate(player_labels[:5]):  # First 5
                    text = await label.inner_text()
                    print(f"  Player {i+1}: {text}")
            else:
                print("\n❌ Players section NOT found")

            # Check for Coach dropdown
            coach_select = await page.query_selector('#coachSelect')
            if coach_select:
                options = await page.query_selector_all('#coachSelect option')
                print(f"\n✓ Coach dropdown found with {len(options)} options")
            else:
                print("\n❌ Coach dropdown NOT found")

            # Check for Location dropdown
            location_select = await page.query_selector('#locationSelect')
            if location_select:
                options = await page.query_selector_all('#locationSelect option')
                print(f"✓ Location dropdown found with {len(options)} options")
                for i, opt in enumerate(options[:5]):
                    text = await opt.inner_text()
                    print(f"  Option {i+1}: {text}")
            else:
                print("❌ Location dropdown NOT found")

            # Check for Session Type pills
            type_pills = await page.query_selector_all('#type-pills-sidebar button')
            print(f"\n✓ Session type pills found: {len(type_pills)}")

            # Check for Date filters
            date_pills = await page.query_selector_all('.date-pill')
            print(f"✓ Date filter pills found: {len(date_pills)}")

            # Scroll to bottom of sidebar
            print("\n=== Scrolling to bottom ===")
            await sidebar.evaluate('(el) => el.scrollTop = el.scrollHeight')
            await asyncio.sleep(1)

            scroll_after = await sidebar.evaluate('(el) => el.scrollTop')
            print(f"Scrolled to: {scroll_after}px")

            # Take screenshot at bottom
            await page.screenshot(path='/home/slach/Pictures/Screenshots/filter-sidebar-bottom.png', full_page=True)
            print("Screenshot saved: filter-sidebar-bottom.png")

            # Scroll to top
            await sidebar.evaluate('(el) => el.scrollTop = 0')
            await asyncio.sleep(1)

            # Take screenshot at top
            await page.screenshot(path='/home/slach/Pictures/Screenshots/filter-sidebar-top.png', full_page=True)
            print("Screenshot saved: filter-sidebar-top.png")

            # Check if Location is visible when scrolled to bottom
            await sidebar.evaluate('(el) => el.scrollTop = el.scrollHeight')
            await asyncio.sleep(0.5)

            location_visible = await page.evaluate('''() => {
                const loc = document.querySelector('#locationSelect');
                if (!loc) return false;
                const rect = loc.getBoundingClientRect();
                return rect.top >= 0 && rect.bottom <= window.innerHeight;
            }''')

            print(f"\n✓ Location dropdown visible when scrolled to bottom: {location_visible}")

        else:
            print("❌ Sidebar NOT found")

        print("\n=== Keep browser open for inspection (10 seconds) ===")
        await asyncio.sleep(10)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_booking_filter_sidebar())
