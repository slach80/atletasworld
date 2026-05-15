"""
Open and display client dashboard for visual inspection.
"""
import asyncio
from playwright.async_api import async_playwright


async def show_dashboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # Desktop view
        desktop = await browser.new_page(viewport={'width': 1920, 'height': 1080})

        print("Opening client dashboard...")
        print("URL: https://atletasperformancecenter.com/portal/dashboard/")

        await desktop.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("\n⚠️  Please log in as client (30 seconds)...")
        await asyncio.sleep(30)

        # Navigate to dashboard
        await desktop.goto('https://atletasperformancecenter.com/portal/dashboard/')
        await asyncio.sleep(3)

        print("\n✅ Dashboard loaded!")
        print("📸 Taking screenshot...")
        await desktop.screenshot(path='/home/slach/Pictures/Screenshots/dashboard-desktop.png', full_page=True)
        print("Saved: ~/Pictures/Screenshots/dashboard-desktop.png")

        # Mobile view
        print("\n📱 Opening mobile view...")
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})
        await mobile.goto('https://atletasperformancecenter.com/portal/dashboard/')
        await asyncio.sleep(3)

        print("📸 Taking mobile screenshot...")
        await mobile.screenshot(path='/home/slach/Pictures/Screenshots/dashboard-mobile.png', full_page=True)
        print("Saved: ~/Pictures/Screenshots/dashboard-mobile.png")

        print("\n" + "="*60)
        print("Browser windows will stay open for inspection.")
        print("Press Ctrl+C to close when done.")
        print("="*60)

        # Keep browsers open
        try:
            await asyncio.sleep(3600)  # Keep open for 1 hour
        except KeyboardInterrupt:
            print("\nClosing browsers...")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(show_dashboard())
