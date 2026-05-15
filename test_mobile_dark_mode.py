"""
Test mobile booking page package section in dark mode.
"""
import asyncio
from playwright.async_api import async_playwright


async def test_mobile_dark_mode():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        mobile = await browser.new_page(viewport={'width': 390, 'height': 844})

        print("Testing mobile dark mode package section...")
        await mobile.goto('https://atletasperformancecenter.com/accounts/login/')
        await asyncio.sleep(2)

        print("⚠️  Log in as client (30 seconds)...")
        await asyncio.sleep(30)

        await mobile.goto('https://atletasperformancecenter.com/portal/book-v2/')
        await asyncio.sleep(3)

        # Take screenshot in light mode
        print("📸 Light mode screenshot...")
        await mobile.screenshot(path='/home/slach/Pictures/Screenshots/mobile-light-package.png')

        # Enable dark mode
        print("🌙 Enabling dark mode...")
        await mobile.click('button[id*="dark"]')  # Click dark mode toggle
        await asyncio.sleep(1)

        # Take screenshot in dark mode
        print("📸 Dark mode screenshot...")
        await mobile.screenshot(path='/home/slach/Pictures/Screenshots/mobile-dark-package.png')

        # Check package banner visibility
        package_banner = await mobile.query_selector('.bg-gradient-to-r')
        if package_banner:
            # Get computed styles
            bg_color = await package_banner.evaluate('el => window.getComputedStyle(el).backgroundColor')
            border_color = await package_banner.evaluate('el => window.getComputedStyle(el).borderColor')
            print(f"Package banner background: {bg_color}")
            print(f"Package banner border: {border_color}")

        print("\n✅ Screenshots saved!")
        print("Check ~/Pictures/Screenshots/mobile-*-package.png")

        await asyncio.sleep(5)
        await browser.close()


if __name__ == '__main__':
    asyncio.run(test_mobile_dark_mode())
