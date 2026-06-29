from __future__ import annotations

from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from ..config import DATA_DIR

AUTH_FILE = DATA_DIR / "amazon_auth.json"
BROWSER_PROFILE = DATA_DIR / "browser_profile"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]
CART_URL = "https://www.amazon.com/gp/cart/view.html"


def base_url_for(url: str) -> str:
    """Scheme+host of an Amazon URL, e.g. https://www.amazon.in . Defaults to .com."""
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return "https://www.amazon.com"


async def verify_auth_state(headless: bool = True, base_url: str = "https://www.amazon.com") -> Tuple[bool, str]:
    if not AUTH_FILE.exists():
        return False, f"Auth file missing: {AUTH_FILE}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=BROWSER_ARGS)
        context = await browser.new_context(storage_state=str(AUTH_FILE), user_agent=USER_AGENT)
        page = await context.new_page()
        try:
            await page.goto(f"{base_url}/gp/css/homepage.html", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1200)
            text = (await page.inner_text("body"))[:5000].lower()
            cookies = await context.cookies()
            has_auth_cookie = any("amazon" in c.get("domain", "") and c.get("name") for c in cookies)
            redirected_to_login = "signin" in page.url.lower() or "ap/signin" in page.url.lower()
            hello = "hello" in text or "your account" in text or "account" in text
            ok = bool(has_auth_cookie and not redirected_to_login and hello)
            lines = [
                f"Auth file: {AUTH_FILE}",
                f"Auth file exists: {AUTH_FILE.exists()}",
                "",
                "Check results:",
                f"{'✓' if has_auth_cookie else '✗'}  Amazon auth cookie",
                f"{'✓' if not redirected_to_login else '✗'}  account page not redirected",
                f"{'✓' if hello else '✗'}  Hello/account greeting in page",
            ]
            return ok, "\n".join(lines)
        finally:
            await context.close()
            await browser.close()


async def reset_amazon_cart(headless: bool = True, max_items: int = 25, cart_url: str = CART_URL) -> str:
    """Deterministically empty the Amazon cart before a run.

    Uses Playwright directly (not browser-use) so it is deterministic and
    side-effect-explicit: it deletes active cart items via the classic cart
    page's Delete controls until the cart is empty. This is the only place the
    explorer is allowed to delete by default, and only when --reset-cart is set,
    so provenance ("cart delta from THIS run") is not muddied by leftovers.

    `cart_url` must be on the same Amazon marketplace as the product under test.
    """
    if not AUTH_FILE.exists():
        return f"Cart reset skipped: auth file missing ({AUTH_FILE})."

    deleted = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=BROWSER_ARGS)
        context = await browser.new_context(storage_state=str(AUTH_FILE), user_agent=USER_AGENT)
        page = await context.new_page()
        try:
            await page.goto(cart_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            # Each Delete click reloads the cart, so re-query from scratch.
            delete_selector = (
                "input[value='Delete'], "
                "input[name^='submit.delete'], "
                "[data-action='delete'] input, "
                "[aria-label^='Delete'], "
                "span[data-action='delete-active'] input"
            )
            for _ in range(max_items):
                body = (await page.inner_text("body")).lower()
                if "your amazon cart is empty" in body or "your shopping cart is empty" in body:
                    break
                btn = page.locator(delete_selector).first
                if await btn.count() == 0:
                    break
                try:
                    await btn.click(timeout=10000)
                    deleted += 1
                    await page.wait_for_timeout(1500)
                except Exception:
                    break
            body = (await page.inner_text("body")).lower()
            empty = "cart is empty" in body
            return (
                f"Cart reset: deleted {deleted} item(s); "
                f"cart_empty={empty}."
            )
        finally:
            await context.close()
            await browser.close()


async def save_login_session(base_url: str = "https://www.amazon.com") -> str:
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            headless=False,
            user_agent=USER_AGENT,
            args=BROWSER_ARGS,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(f"{base_url}/", wait_until="domcontentloaded")
        print(f"\n  Browser profile: {BROWSER_PROFILE}")
        print(f"  Opening {base_url} in a persistent browser session.")
        print("  Log in manually — handle OTP/CAPTCHA in the browser window.")
        print("  Come back here and press Enter when you see your Amazon home page.\n")
        input("  Press Enter once you are logged into Amazon... ")
        await context.storage_state(path=str(AUTH_FILE))
        await context.close()
    ok, msg = await verify_auth_state(headless=True, base_url=base_url)
    if ok:
        return msg + f"\n\n  Session verified — you are signed in.\n  Auth state saved to: {AUTH_FILE}\n"
    return msg + "\n\n  Session could not be verified. Try login again.\n"
