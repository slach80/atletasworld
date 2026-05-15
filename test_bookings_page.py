"""
Test bookings page layout on production - check for issues.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_bookings_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # Test both desktop and mobile
        print("="*60)
        print("TESTING DESKTOP VIEW")
        print("="*60)
        desktop = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        await desktop.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("\n⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await desktop.goto('https://atletasperformancecenter.com/portal/bookings/')
        await asyncio.sleep(3)

        # Check Upcoming Sessions section
        upcoming = await desktop.query_selector('.bg-white.rounded-xl.shadow-md.p-8.mb-8')
        if upcoming:
            upcoming_info = await upcoming.evaluate('''(el) => {
                const style = window.getComputedStyle(el);
                return {
                    width: el.offsetWidth,
                    padding: style.padding,
                    marginBottom: style.marginBottom
                };
            }''')
            print(f"\n✓ Upcoming Sessions section found")
            print(f"  Width: {upcoming_info['width']}px")
            print(f"  Padding: {upcoming_info['padding']}")
            print(f"  Margin-bottom: {upcoming_info['marginBottom']}")

        # Check Past Sessions section
        past = await desktop.query_selector('.bg-white.rounded-xl.shadow-md.p-8')
        if past:
            past_info = await past.evaluate('''(el) => {
                const style = window.getComputedStyle(el);
                return {
                    width: el.offsetWidth,
                    padding: style.padding
                };
            }''')
            print(f"\n✓ Past Sessions section found")
            print(f"  Width: {past_info['width']}px")
            print(f"  Padding: {past_info['padding']}")

        # Check if they align
        if upcoming and past:
            alignment = await desktop.evaluate('''() => {
                const sections = document.querySelectorAll('.bg-white.rounded-xl.shadow-md');
                if (sections.length >= 2) {
                    const rect1 = sections[0].getBoundingClientRect();
                    const rect2 = sections[1].getBoundingClientRect();
                    return {
                        upcoming_left: rect1.left,
                        upcoming_width: rect1.width,
                        past_left: rect2.left,
                        past_width: rect2.width,
                        aligned: Math.abs(rect1.left - rect2.left) < 2 && Math.abs(rect1.width - rect2.width) < 2
                    };
                }
                return null;
            }''')

            if alignment:
                print(f"\n=== Alignment Check ===")
                print(f"Upcoming: left={alignment['upcoming_left']}, width={alignment['upcoming_width']}")
                print(f"Past: left={alignment['past_left']}, width={alignment['past_width']}")
                print(f"Aligned: {alignment['aligned']}")

                if not alignment['aligned']:
                    print("\n❌ SECTIONS NOT ALIGNED!")
                else:
                    print("\n✓ Sections properly aligned")

        await desktop.screenshot(path='/home/slach/Pictures/Screenshots/bookings-desktop.png', full_page=True)
        print("\nScreenshot saved: bookings-desktop.png")

        # Mobile test
        print("\n" + "="*60)
        print("TESTING MOBILE VIEW")
        print("="*60)
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        await mobile.goto('https://atletasperformancecenter.com/portal/bookings/')
        await asyncio.sleep(3)

        # Check booking cards
        booking_cards = await mobile.query_selector_all('.border-2.border-gray-200.rounded-xl')
        print(f"\n✓ Found {len(booking_cards)} booking cards")

        if len(booking_cards) > 0:
            # Check first card layout
            card_info = await booking_cards[0].evaluate('''(el) => {
                const rect = el.getBoundingClientRect();
                return {
                    width: rect.width,
                    height: rect.height,
                    padding: window.getComputedStyle(el).padding
                };
            }''')
            print(f"  Card width: {card_info['width']}px")
            print(f"  Card height: {card_info['height']}px")
            print(f"  Card padding: {card_info['padding']}")

            # Check if action buttons are visible
            buttons = await booking_cards[0].query_selector_all('button, a')
            print(f"  Action buttons in card: {len(buttons)}")

        await mobile.screenshot(path='/home/slach/Pictures/Screenshots/bookings-mobile.png', full_page=True)
        print("\nScreenshot saved: bookings-mobile.png")

        # Check specific elements
        print("\n=== Checking Specific Elements ===")

        # Check date badges
        date_badges = await mobile.query_selector_all('.bg-purple-100.rounded-lg')
        print(f"✓ Date badges found: {len(date_badges)}")

        # Check status badges
        status_badges = await mobile.query_selector_all('.rounded-full')
        print(f"✓ Status badges found: {len(status_badges)}")

        # Check grid layout for buttons
        button_grids = await mobile.query_selector_all('.grid.grid-cols-1.sm\\:grid-cols-2')
        print(f"✓ Button grids found: {len(button_grids)}")

        print("\n=== Keep browser open for inspection (10 seconds) ===")
        await asyncio.sleep(10)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_bookings_page())
