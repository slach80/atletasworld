"""
Test location filter dropdown to check for duplicates.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_location_filter():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # Test desktop view
        print("="*60)
        print("TESTING DESKTOP LOCATION FILTER")
        print("="*60)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        await page.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("\n⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await page.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(5)  # Wait for slots to load

        # Check desktop location dropdown
        desktop_select = await page.query_selector('#locationSelect')
        if desktop_select:
            options = await desktop_select.query_selector_all('option')
            print(f"\n✓ Desktop location dropdown found with {len(options)} options:")
            for i, opt in enumerate(options):
                value = await opt.get_attribute('value')
                text = await opt.inner_text()
                print(f"  {i+1}. value='{value}' text='{text}'")
        else:
            print("\n❌ Desktop location dropdown NOT found")

        # Check for duplicates
        if desktop_select:
            option_texts = []
            for opt in options:
                text = await opt.inner_text()
                option_texts.append(text)

            duplicates = [x for x in option_texts if option_texts.count(x) > 1]
            unique_duplicates = list(set(duplicates))

            if unique_duplicates:
                print(f"\n❌ DUPLICATES FOUND: {unique_duplicates}")
            else:
                print(f"\n✓ No duplicates found")

        # Test mobile view
        print("\n" + "="*60)
        print("TESTING MOBILE LOCATION FILTER")
        print("="*60)
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        await mobile.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(5)

        # Open mobile filter sheet
        filter_btn = await mobile.query_selector('#mobile-filter-btn')
        if filter_btn:
            await filter_btn.click()
            await asyncio.sleep(1)
            print("✓ Opened mobile filter sheet")

            mobile_select = await mobile.query_selector('#locationSelectMobile')
            if mobile_select:
                options = await mobile_select.query_selector_all('option')
                print(f"\n✓ Mobile location dropdown found with {len(options)} options:")
                for i, opt in enumerate(options):
                    value = await opt.get_attribute('value')
                    text = await opt.inner_text()
                    print(f"  {i+1}. value='{value}' text='{text}'")

                # Check for duplicates
                option_texts = []
                for opt in options:
                    text = await opt.inner_text()
                    option_texts.append(text)

                duplicates = [x for x in option_texts if option_texts.count(x) > 1]
                unique_duplicates = list(set(duplicates))

                if unique_duplicates:
                    print(f"\n❌ DUPLICATES FOUND: {unique_duplicates}")
                else:
                    print(f"\n✓ No duplicates found")
            else:
                print("\n❌ Mobile location dropdown NOT found")

        print("\n=== Keep browser open for inspection (15 seconds) ===")
        await asyncio.sleep(15)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_location_filter())
