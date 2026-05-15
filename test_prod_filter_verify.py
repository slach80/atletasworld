"""
Verify the filter fix is working on production after deploy.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_prod_filter_after_fix():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        print("Testing production after filter fix...")
        await page.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        # Force reload to clear cache
        await page.goto('https://atletasperformancecenter.com/portal/book-v2/', wait_until='networkidle')
        await page.reload(wait_until='networkidle')
        await asyncio.sleep(3)

        print("\n=== Checking slot data after fix ===")

        # Check if session_type_id is now populated
        slot_data = await page.evaluate('''() => {
            const firstSlot = Object.values(slotMap || {})[0];
            return {
                total_slots: Object.keys(slotMap || {}).length,
                first_slot: firstSlot,
                has_session_type_id: firstSlot ? (firstSlot.session_type_id !== undefined) : false,
                has_coach_id: firstSlot ? (firstSlot.coach_id !== undefined) : false,
                has_location_id: firstSlot ? (firstSlot.location_id !== undefined) : false
            };
        }''')

        print(f"Total slots: {slot_data['total_slots']}")
        print(f"Has session_type_id: {slot_data['has_session_type_id']}")
        print(f"Has coach_id: {slot_data['has_coach_id']}")
        print(f"Has location_id: {slot_data['has_location_id']}")

        if slot_data['first_slot']:
            print(f"\nFirst slot sample:")
            for key, val in list(slot_data['first_slot'].items())[:10]:
                print(f"  {key}: {val}")

        # Count sessions by type
        sessions_by_type = await page.evaluate('''() => {
            const counts = {};
            for (const slot of Object.values(slotMap || {})) {
                const typeId = slot.session_type_id;
                if (typeId) {
                    counts[typeId] = (counts[typeId] || 0) + 1;
                }
            }
            return counts;
        }''')

        print(f"\n=== Sessions by Type (should NOT be undefined) ===")
        for type_id, count in list(sessions_by_type.items())[:10]:
            print(f"Type ID {type_id}: {count} sessions")

        if 'undefined' in sessions_by_type or not sessions_by_type:
            print("\n❌ STILL BROKEN: session_type_id is undefined!")
            print("Possible causes:")
            print("  1. Browser cached old JavaScript")
            print("  2. Django template cache not cleared")
            print("  3. API response not updated")
        else:
            print("\n✓ session_type_id is now populated correctly!")

            # Test actual filtering
            print("\n=== Testing filter functionality ===")

            # Get a type that has sessions
            first_type_id = list(sessions_by_type.keys())[0]
            expected_count = sessions_by_type[first_type_id]

            print(f"Clicking filter for type ID {first_type_id} (expect {expected_count} sessions)...")

            await page.click(f'[data-type-pill="{first_type_id}"]')
            await asyncio.sleep(2)

            # Count visible session cards
            session_cards = await page.query_selector_all('#slots-container > div')
            visible_count = len(session_cards)

            print(f"✓ Visible session groups after filter: {visible_count}")

            # Check for "No sessions found"
            no_sessions = await page.query_selector('text="No sessions found"')
            if no_sessions:
                print("❌ Shows 'No sessions found' - filter still broken!")
            else:
                print("✓ Sessions are displayed - filter works!")

            await page.screenshot(path='/home/slach/Pictures/Screenshots/prod-verify-filtered.png', full_page=True)

        print("\nKeep browser open for inspection (10 seconds)...")
        await asyncio.sleep(10)

        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_prod_filter_after_fix())
