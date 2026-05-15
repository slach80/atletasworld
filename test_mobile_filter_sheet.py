"""
Test mobile filter bottom sheet on production - check for cutoff and missing elements.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_mobile_filter_sheet():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        print("Testing MOBILE filter bottom sheet on production...")
        await mobile.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await mobile.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(3)

        print("\n=== Opening Mobile Filter Sheet ===")

        # Click filter button
        filter_btn = await mobile.query_selector('#mobile-filter-btn')
        if filter_btn:
            await filter_btn.click()
            await asyncio.sleep(1)
            print("✓ Clicked filter button")

            # Check if sheet is visible
            sheet = await mobile.query_selector('#mobile-filter-sheet')
            if sheet:
                is_visible = await sheet.is_visible()
                print(f"✓ Filter sheet visible: {is_visible}")

                # Get sheet dimensions
                sheet_info = await sheet.evaluate('''(el) => {
                    return {
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        scrollTop: el.scrollTop,
                        hasOverflow: el.scrollHeight > el.clientHeight
                    };
                }''')

                print(f"\nSheet Dimensions:")
                print(f"  Content height: {sheet_info['scrollHeight']}px")
                print(f"  Visible height: {sheet_info['clientHeight']}px")
                print(f"  Has overflow: {sheet_info['hasOverflow']}")

                # Check for Players section
                players_section = await mobile.query_selector('#mobile-filter-sheet label:text("Players")')
                if players_section:
                    print("\n✓ Players section found")
                else:
                    print("\n❌ Players section NOT found in mobile sheet")

                # Check for Coach dropdown
                coach_select = await mobile.query_selector('#coachSelectMobile')
                if coach_select:
                    options = await mobile.query_selector_all('#coachSelectMobile option')
                    print(f"✓ Coach dropdown found with {len(options)} options")
                else:
                    print("❌ Coach dropdown NOT found in mobile sheet")

                # Check for Location dropdown
                location_select = await mobile.query_selector('#locationSelectMobile')
                if location_select:
                    options = await mobile.query_selector_all('#locationSelectMobile option')
                    print(f"✓ Location dropdown found with {len(options)} options")
                    for i, opt in enumerate(options[:3]):
                        text = await opt.inner_text()
                        print(f"  Option {i+1}: {text}")
                else:
                    print("❌ Location dropdown NOT found in mobile sheet")

                # Check for Session Type pills
                type_pills = await mobile.query_selector_all('#type-pills-mobile button')
                print(f"\n✓ Session type pills found: {len(type_pills)}")

                # Check for Date filters
                date_pills = await mobile.query_selector_all('#mobile-filter-sheet .date-pill')
                print(f"✓ Date filter pills found: {len(date_pills)}")

                # Take screenshot at current position
                await mobile.screenshot(path='/home/slach/Pictures/Screenshots/mobile-filter-top.png', full_page=False)
                print("\nScreenshot saved: mobile-filter-top.png")

                # Scroll to bottom of sheet
                print("\n=== Scrolling to bottom ===")
                await sheet.evaluate('(el) => el.scrollTop = el.scrollHeight')
                await asyncio.sleep(1)

                scroll_after = await sheet.evaluate('(el) => el.scrollTop')
                print(f"Scrolled to: {scroll_after}px")

                # Take screenshot at bottom
                await mobile.screenshot(path='/home/slach/Pictures/Screenshots/mobile-filter-bottom.png', full_page=False)
                print("Screenshot saved: mobile-filter-bottom.png")

                # Check what's visible at bottom
                elements_at_bottom = await mobile.evaluate('''() => {
                    const sheet = document.querySelector('#mobile-filter-sheet');
                    const rect = sheet.getBoundingClientRect();
                    const bottom = rect.bottom;

                    return {
                        location_visible: !!document.querySelector('#locationSelectMobile') &&
                            document.querySelector('#locationSelectMobile').getBoundingClientRect().top < bottom,
                        date_visible: !!document.querySelector('#mobile-filter-sheet .date-pill') &&
                            document.querySelector('#mobile-filter-sheet .date-pill').getBoundingClientRect().top < bottom,
                        apply_btn_visible: !!document.querySelector('#mobile-filter-sheet button:text("Apply Filters")') &&
                            document.querySelector('#mobile-filter-sheet button:text("Apply Filters")').getBoundingClientRect().top < bottom
                    };
                }''')

                print(f"\nElements visible at bottom:")
                print(f"  Location dropdown: {elements_at_bottom.get('location_visible', 'N/A')}")
                print(f"  Date filters: {elements_at_bottom.get('date_visible', 'N/A')}")
                print(f"  Apply button: {elements_at_bottom.get('apply_btn_visible', 'N/A')}")

            else:
                print("❌ Filter sheet NOT found")
        else:
            print("❌ Filter button NOT found")

        print("\n=== Keep browser open for inspection (10 seconds) ===")
        await asyncio.sleep(10)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_mobile_filter_sheet())
