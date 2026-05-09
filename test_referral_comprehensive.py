#!/usr/bin/env python3
"""
Comprehensive Playwright test for referral program (no auth required).
Tests public-facing elements and error-free loading.
"""
import asyncio
from playwright.async_api import async_playwright

SITE_URL = "https://atletasperformancecenter.com"

async def test_comprehensive():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("🧪 Comprehensive Referral Program Test\n")

        # Test 1: Signup page with referral code parameter
        print("1️⃣ Testing signup with referral code parameter...")
        await page.goto(f"{SITE_URL}/accounts/signup/?ref=TESTCODE123")
        await page.wait_for_load_state("networkidle")

        # Check for errors
        has_error = await page.query_selector("text=Server Error")
        if has_error:
            print("   ❌ Server Error (500) on signup page!")
            await page.screenshot(path="/tmp/signup_error.png")
        else:
            print("   ✓ Signup page loaded without errors")

            # Check if hidden referral field exists
            hidden_field = await page.query_selector('input[name="referral_code"]')
            if hidden_field:
                value = await hidden_field.get_attribute('value')
                print(f"   ✓ Hidden referral_code field found (value: {value})")
            else:
                print("   ⚠️  Hidden referral_code field not found")

        await page.screenshot(path="/tmp/signup_with_ref.png")
        print("   📸 Screenshot: /tmp/signup_with_ref.png")

        # Test 2: Middleware - check if ref param is being captured
        print("\n2️⃣ Testing middleware ref parameter capture...")
        await page.goto(f"{SITE_URL}/?ref=MIDDLEWARE123")
        await page.wait_for_load_state("networkidle")

        # Check cookies/storage (middleware sets session)
        cookies = await context.cookies()
        print(f"   ℹ️  Session cookies present: {len([c for c in cookies if 'session' in c['name']])} cookie(s)")

        # Navigate to signup to see if ref persists
        await page.goto(f"{SITE_URL}/accounts/signup/")
        await page.wait_for_load_state("networkidle")
        hidden_field = await page.query_selector('input[name="referral_code"]')
        if hidden_field:
            value = await hidden_field.get_attribute('value')
            if value == "MIDDLEWARE123":
                print("   ✓ Middleware successfully captured and persisted ref code!")
            else:
                print(f"   ⚠️  Ref code in field: {value} (expected: MIDDLEWARE123)")
        else:
            print("   ⚠️  Could not verify middleware persistence")

        # Test 3: Portal pages redirect properly (unauthenticated)
        print("\n3️⃣ Testing portal authentication redirects...")
        portal_urls = [
            ("/portal/referral/", "Client"),
            ("/coach-portal/referral/", "Coach"),
            ("/owner-portal/referrals/", "Owner"),
        ]

        for url, portal_name in portal_urls:
            await page.goto(f"{SITE_URL}{url}")
            await page.wait_for_load_state("networkidle")

            # Should redirect to login
            current_url = page.url
            if "login" in current_url.lower():
                print(f"   ✓ {portal_name} portal - redirects to login")
            else:
                print(f"   ⚠️  {portal_name} portal - unexpected redirect: {current_url}")

        # Test 4: Check for JavaScript errors on key pages
        print("\n4️⃣ Testing for JavaScript errors...")
        test_pages = [
            "/",
            "/accounts/signup/",
            "/accounts/login/",
        ]

        for url in test_pages:
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.on("console", lambda msg: errors.append(f"Console {msg.type}: {msg.text}") if msg.type in ["error", "warning"] else None)

            await page.goto(f"{SITE_URL}{url}")
            await page.wait_for_load_state("networkidle")

            if errors:
                print(f"   ⚠️  {url} - {len(errors)} error(s):")
                for err in errors[:3]:  # Show first 3
                    print(f"      - {err[:100]}")
            else:
                print(f"   ✓ {url} - no JS errors")

        # Test 5: Mobile responsiveness check
        print("\n5️⃣ Testing mobile responsiveness...")
        await context.close()
        mobile_context = await browser.new_context(
            viewport={"width": 375, "height": 667},  # iPhone SE
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15"
        )
        mobile_page = await mobile_context.new_page()

        await mobile_page.goto(f"{SITE_URL}/accounts/signup/?ref=MOBILE123")
        await mobile_page.wait_for_load_state("networkidle")
        await mobile_page.screenshot(path="/tmp/signup_mobile.png")

        # Check if mobile menu button exists (when logged in, client portal would show this)
        has_error = await mobile_page.query_selector("text=Server Error")
        if not has_error:
            print("   ✓ Mobile signup loads without errors")
            print("   📸 Screenshot: /tmp/signup_mobile.png")
        else:
            print("   ❌ Mobile signup has errors")

        await mobile_context.close()

        print("\n✅ Comprehensive test complete!")
        print("\nScreenshots saved:")
        print("  - /tmp/signup_with_ref.png")
        print("  - /tmp/signup_mobile.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_comprehensive())
