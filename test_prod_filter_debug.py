"""
Debug production filter behavior - check JavaScript console and actual filtering.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_prod_filter_debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # Capture console messages
        console_messages = []
        errors = []

        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        page.on('console', lambda msg: console_messages.append(f"{msg.type}: {msg.text}"))
        page.on('pageerror', lambda err: errors.append(str(err)))

        print("Navigating to production...")
        await page.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await page.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(3)

        # Check JavaScript state
        js_state = await page.evaluate('''() => {
            return {
                slotMapSize: Object.keys(slotMap || {}).length,
                sessionTypesCount: (sessionTypes || []).length,
                activeTypesSize: (activeTypes || new Set()).size,
                activeCoach: activeCoach || '',
                activeDateFilter: activeDateFilter || '',
                activeLocation: activeLocation || '',
                cartSize: (cart || []).length
            };
        }''')

        print("\n=== JavaScript State ===")
        for key, val in js_state.items():
            print(f"{key}: {val}")

        # Get first 5 session types
        session_types = await page.evaluate('''() => {
            return (sessionTypes || []).slice(0, 10).map(st => ({
                id: st.id,
                name: st.name
            }));
        }''')

        print("\n=== First 10 Session Types ===")
        for st in session_types:
            print(f"ID {st['id']}: {st['name']}")

        # Count sessions by type in slotMap
        sessions_by_type = await page.evaluate('''() => {
            const counts = {};
            for (const [key, slot] of Object.entries(slotMap || {})) {
                const typeId = slot.session_type_id;
                counts[typeId] = (counts[typeId] || 0) + 1;
            }
            return counts;
        }''')

        print("\n=== Sessions by Type (first 10) ===")
        for type_id, count in list(sessions_by_type.items())[:10]:
            print(f"Type ID {type_id}: {count} sessions")

        # Now test clicking a session type that HAS sessions
        # Find which type has the most sessions
        if sessions_by_type:
            most_common_type = max(sessions_by_type.items(), key=lambda x: x[1])
            type_id, count = most_common_type
            print(f"\n=== Testing filter for Type ID {type_id} ({count} sessions) ===")

            # Click that type's pill
            await page.click(f'[data-type-pill="{type_id}"]')
            await asyncio.sleep(2)

            # Count visible sessions
            visible = len(await page.query_selector_all('#slots-container > div'))
            print(f"✓ Clicked filter for type {type_id}")
            print(f"✓ Visible session groups: {visible}")

            await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-debug-filtered.png', full_page=True)

            # Check if "No sessions found" appears
            no_sessions = await page.query_selector('text="No sessions found"')
            if no_sessions:
                print("❌ Shows 'No sessions found' even though sessions exist!")
            else:
                print("✓ Sessions are displayed correctly")

        # Check console for errors
        if errors:
            print("\n=== JavaScript Errors ===")
            for err in errors:
                print(f"ERROR: {err}")

        if console_messages:
            print("\n=== Console Messages (last 20) ===")
            for msg in console_messages[-20:]:
                print(msg)

        print("\n=== Keep browser open for 10 seconds ===")
        await asyncio.sleep(10)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_prod_filter_debug())
