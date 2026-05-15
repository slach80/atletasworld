"""
Check bookings page HTML structure to diagnose alignment issue.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_bookings_structure():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        await page.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await page.goto('https://atletasperformancecenter.com/portal/bookings/')
        await asyncio.sleep(3)

        # Get the outer container info
        outer_container = await page.query_selector('.max-w-6xl')
        if outer_container:
            outer_info = await outer_container.evaluate('''(el) => {
                const rect = el.getBoundingClientRect();
                return {
                    width: rect.width,
                    left: rect.left,
                    classes: el.className,
                    childCount: el.children.length
                };
            }''')
            print("\n=== Outer Container (max-w-6xl) ===")
            print(f"Width: {outer_info['width']}px")
            print(f"Left: {outer_info['left']}px")
            print(f"Classes: {outer_info['classes']}")
            print(f"Direct children: {outer_info['childCount']}")

        # Get Upcoming Sessions parent
        upcoming = await page.query_selector('.bg-white.rounded-xl.shadow-md.p-8.mb-8')
        if upcoming:
            upcoming_parent = await upcoming.evaluate('''(el) => {
                const parent = el.parentElement;
                const parentRect = parent.getBoundingClientRect();
                const rect = el.getBoundingClientRect();
                return {
                    parent_class: parent.className,
                    parent_width: parentRect.width,
                    parent_left: parentRect.left,
                    self_width: rect.width,
                    self_left: rect.left
                };
            }''')
            print("\n=== Upcoming Sessions ===")
            print(f"Parent class: {upcoming_parent['parent_class']}")
            print(f"Parent width: {upcoming_parent['parent_width']}px, left: {upcoming_parent['parent_left']}px")
            print(f"Self width: {upcoming_parent['self_width']}px, left: {upcoming_parent['self_left']}px")

        # Get Past Sessions (without mb-8 class)
        past_sections = await page.query_selector_all('.bg-white.rounded-xl.shadow-md.p-8')
        if len(past_sections) >= 2:
            past = past_sections[1]  # Second one should be Past Sessions
            past_info = await past.evaluate('''(el) => {
                const parent = el.parentElement;
                const parentRect = parent.getBoundingClientRect();
                const rect = el.getBoundingClientRect();

                // Check if parent is the max-w-6xl container
                let container = parent;
                let depth = 0;
                while (container && depth < 5) {
                    if (container.className && container.className.includes('max-w-6xl')) {
                        break;
                    }
                    container = container.parentElement;
                    depth++;
                }

                return {
                    parent_class: parent.className,
                    parent_width: parentRect.width,
                    parent_left: parentRect.left,
                    self_width: rect.width,
                    self_left: rect.left,
                    has_max_w_6xl_ancestor: container && container.className.includes('max-w-6xl'),
                    depth_to_container: depth
                };
            }''')
            print("\n=== Past Sessions ===")
            print(f"Parent class: {past_info['parent_class']}")
            print(f"Parent width: {past_info['parent_width']}px, left: {past_info['parent_left']}px")
            print(f"Self width: {past_info['self_width']}px, left: {past_info['self_left']}px")
            print(f"Has max-w-6xl ancestor: {past_info['has_max_w_6xl_ancestor']}")
            print(f"Depth to container: {past_info['depth_to_container']}")

        # Check if there are any unclosed divs by counting
        div_check = await page.evaluate('''() => {
            const container = document.querySelector('.max-w-6xl');
            if (!container) return null;

            const html = container.innerHTML;
            const openDivs = (html.match(/<div/g) || []).length;
            const closeDivs = (html.match(/<\\/div>/g) || []).length;

            return {
                open_divs: openDivs,
                close_divs: closeDivs,
                balanced: openDivs === closeDivs
            };
        }''')

        if div_check:
            print("\n=== Div Balance Check ===")
            print(f"Opening <div> tags: {div_check['open_divs']}")
            print(f"Closing </div> tags: {div_check['close_divs']}")
            print(f"Balanced: {div_check['balanced']}")

        print("\n=== Keep browser open for inspection (15 seconds) ===")
        await asyncio.sleep(15)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_bookings_structure())
