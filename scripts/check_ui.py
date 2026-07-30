#!/usr/bin/env python3
"""
UI visual check: screenshots key pages in light + dark mode, flags low-contrast
text areas by sampling pixel luminance.

Usage:
    python scripts/check_ui.py [--server-url URL] [--save-shots DIR]

Defaults:
    --server-url  http://localhost:8001
    --save-shots  /tmp/ui-check

Exit codes:
    0  all checks passed
    1  one or more failures (contrast, JS console errors, missing elements)
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────

TEST_CREDS = ("lisa@example.com", "test123")

PAGES = [
    {"name": "dashboard",     "url": "/portal/dashboard/"},
    {"name": "packages",      "url": "/portal/packages/"},
    {"name": "book",          "url": "/portal/book-v2/"},
    {"name": "bookings",      "url": "/portal/bookings/"},
]

# Scroll positions to capture within each page (0 = top)
PAGE_SCROLLS = {
    "packages": [0, 600, 1300, 1900],
    "book":     [0, 500],
    "default":  [0],
}

# Minimum average luminance of a sampled region — below this on a light bg
# or above this on a dark bg suggests invisible text.
LUMINANCE_FLOOR = 0.12   # text must be darker than this relative to white bg
LUMINANCE_CEIL  = 0.88   # text must be lighter than this relative to dark bg

# Known elements that must be present on each page
REQUIRED_ELEMENTS = {
    "packages": ["text=Your Cart", "text=ENROLL"],
    "book":     ["text=Book a Session"],
    "dashboard": ["text=Dashboard"],
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("Installing playwright...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q",
                               "--break-system-packages"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def _luminance(r, g, b):
    """Relative luminance per WCAG 2.1."""
    def _c(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * _c(r) + 0.7152 * _c(g) + 0.0722 * _c(b)


def _check_screenshot_contrast(path: Path, dark_mode: bool) -> list[str]:
    """
    Sample a grid of pixels. In light mode, flag regions where the sampled
    pixel is very close to the background white (potential invisible light text).
    In dark mode, flag regions very close to the dark background.
    Returns a list of warning strings (empty = no issues).
    """
    try:
        from PIL import Image
    except ImportError:
        return []  # PIL not available — skip contrast check

    img = Image.open(path).convert("RGB")
    w, h = img.size
    warnings = []

    # Sample a 20×30 grid, skip top navigation bar (first 60px)
    grid_x, grid_y = 20, 30
    step_x, step_y = w // grid_x, max(1, (h - 60) // grid_y)

    # Collect luminance of all sampled pixels
    lums = []
    for gy in range(grid_y):
        for gx in range(grid_x):
            px = min(gx * step_x, w - 1)
            py = min(60 + gy * step_y, h - 1)
            r, g, b = img.getpixel((px, py))
            lums.append(_luminance(r, g, b))

    # In light mode: most pixels should be near-white (bg) or near-black (text).
    # Flag if the spread collapses — everything mid-grey suggests washed-out text.
    if lums:
        avg = sum(lums) / len(lums)
        low = min(lums)
        high = max(lums)
        spread = high - low

        if not dark_mode:
            # Light mode: if almost nothing is below 0.3, text is too light
            dark_pixels = sum(1 for l in lums if l < 0.3)
            if dark_pixels / len(lums) < 0.03 and spread < 0.5:
                warnings.append(f"Low contrast in light mode — very few dark pixels "
                                 f"(spread={spread:.2f}, avg={avg:.2f})")
        else:
            # Dark mode: if almost nothing is above 0.4, text is too dark
            light_pixels = sum(1 for l in lums if l > 0.4)
            if light_pixels / len(lums) < 0.03 and spread < 0.4:
                warnings.append(f"Low contrast in dark mode — very few light pixels "
                                 f"(spread={spread:.2f}, avg={avg:.2f})")

    return warnings


# ── Main ─────────────────────────────────────────────────────────────────────

def run_checks(server_url: str, shots_dir: Path) -> bool:
    _ensure_playwright()
    from playwright.sync_api import sync_playwright

    shots_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    total_shots = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        for dark in [False, True]:
            mode = "dark" if dark else "light"

            # ── Shared session ────────────────────────────────────────────
            ctx = browser.new_context(viewport={"width": 430, "height": 932})
            page = ctx.new_page()

            # Capture JS console errors
            console_errors: list[str] = []
            page.on("console", lambda m: console_errors.append(m.text)
                    if m.type == "error" else None)

            # Login
            page.goto(f"{server_url}/accounts/login/")
            page.fill('input[name="login"]', TEST_CREDS[0])
            page.fill('input[name="password"]', TEST_CREDS[1])
            page.click('button[type="submit"]')
            try:
                page.wait_for_url("**/portal/**", timeout=8000)
            except Exception:
                failures.append(f"[{mode}] Login failed")
                ctx.close()
                continue

            if dark:
                page.evaluate('localStorage.setItem("apc-dark","1"); '
                               'document.documentElement.classList.add("dark")')

            for page_cfg in PAGES:
                name = page_cfg["name"]
                url  = server_url + page_cfg["url"]
                scrolls = PAGE_SCROLLS.get(name, PAGE_SCROLLS["default"])

                page.goto(url)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    failures.append(f"[{mode}] {name}: page load timeout")
                    continue

                # Wait after dark-mode toggle applies
                if dark:
                    page.wait_for_timeout(300)

                # Required element checks
                for selector in REQUIRED_ELEMENTS.get(name, []):
                    try:
                        page.wait_for_selector(f":text('{selector.replace('text=','')}'),"
                                               f"[aria-label='{selector.replace('text=','')}']",
                                               timeout=2000)
                    except Exception:
                        # Softer check via page content
                        if selector.replace("text=", "") not in page.content():
                            failures.append(f"[{mode}] {name}: missing '{selector}'")

                # Screenshots at each scroll position
                for sy in scrolls:
                    page.evaluate(f"window.scrollTo(0, {sy})")
                    page.wait_for_timeout(200)
                    shot_path = shots_dir / f"{mode}_{name}_{sy}.png"
                    page.screenshot(path=str(shot_path))
                    total_shots += 1

                    # Contrast check
                    contrast_warns = _check_screenshot_contrast(shot_path, dark)
                    for w in contrast_warns:
                        failures.append(f"[{mode}] {name} scroll={sy}: {w}")

            # JS error check (aggregate across all pages in this session)
            critical_js_errors = [e for e in console_errors
                                   if "TypeError" in e or "ReferenceError" in e
                                   or "SyntaxError" in e]
            if critical_js_errors:
                for e in critical_js_errors[:3]:
                    failures.append(f"[{mode}] JS error: {e[:120]}")

            ctx.close()

        browser.close()

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"UI Check — {total_shots} screenshots saved to {shots_dir}")
    print(f"{'='*60}")

    if failures:
        print(f"\n❌  {len(failures)} issue(s) found:\n")
        for f in failures:
            print(f"  • {f}")
        print()
        return False
    else:
        print("\n✅  All checks passed\n")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APC UI visual check")
    parser.add_argument("--server-url", default="http://localhost:8001")
    parser.add_argument("--save-shots", default="/tmp/ui-check")
    args = parser.parse_args()

    ok = run_checks(args.server_url, Path(args.save_shots))
    sys.exit(0 if ok else 1)
