"""
Open and display mobile client dashboard for visual inspection.
"""
import asyncio
from playwright.async_api import async_playwright


async def show_mobile_dashboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        # Mobile view only (iPhone 12/13/14 size)
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        print("Opening mobile client dashboard...")
        print("URL: https://atletasperformancecenter.com/portal/dashboard/")
        print("Viewport: 390x844 (iPhone)")

        await mobile.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("\n⚠️  Please log in as client (30 seconds)...")
        await asyncio.sleep(30)

        # Navigate to dashboard
        await mobile.goto('https://atletasperformancecenter.com/portal/dashboard/')
        await asyncio.sleep(3)

        print("\n✅ Mobile dashboard loaded!")
        print("📸 Taking screenshot...")
        await mobile.screenshot(path='/home/slach/Pictures/Screenshots/mobile-dashboard-full.png', full_page=True)
        print("Saved: ~/Pictures/Screenshots/mobile-dashboard-full.png")

        print("\n" + "="*60)
        print("📱 Mobile browser window is open for inspection.")
        print("Press Ctrl+C to close when done.")
        print("="*60)

        # Keep browser open
        try:
            await asyncio.sleep(3600)  # Keep open for 1 hour
        except KeyboardInterrupt:
            print("\nClosing browser...")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(show_mobile_dashboard())
