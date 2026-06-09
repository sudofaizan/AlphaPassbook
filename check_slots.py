#!/usr/bin/env python3
"""
Passport India - Fast Slot Checker & Auto Booker
Phase 1 : UI login once (handles double-login fix automatically)
Phase 2 : Direct API polling via fetch() inside browser context
          - no page navigation per loop → ~200-400 ms per check
          - reCAPTCHA solved by the live browser automatically
          - re-login when session expires or rate-limited too hard
"""

import asyncio
import json
import random
import time
from datetime import datetime
from playwright.async_api import async_playwright, Page

# ── Configuration ──────────────────────────────────────────────────────────────
USERNAME        = "NATIONALPS13"
PASSWORD        = "Pass@1236"
APP_REF_NO      = "26-0065836197"   # update if needed
PFC_LOCATION    = 291
PBO_ID          = "6"

REQUIRED_DATES  = [
    "08/06/2026", "09/06/2026", "10/06/2026",
    "12/06/2026", "13/06/2026", "14/06/2026",
    "15/06/2026", "16/06/2026", "17/06/2026",
    "18/06/2026", "19/06/2026", 
]

# Delay between API calls (ms). Lower = faster but higher risk of block.
RECAPTCHA_SITEKEY = "6LfHkpkpAAAAAGzwnRDa9DiuCz6Yb9Cw8zL99TCo"

POLL_DELAY_MS   = 300
# After how many "Please try again later" in a row to back off
BLOCK_THRESHOLD = 5
# Back-off sleep when blocked (seconds)
BACKOFF_SECS    = 15
# ───────────────────────────────────────────────────────────────────────────────

PRELOGIN_URL    = "https://services1.passportindia.gov.in/forms/PreLogin"
SLOTS_API_URL   = "https://api1.passportindia.gov.in/v1/secure/showslotsbylocation"
PORTAL_ORIGIN   = "https://services1.passportindia.gov.in"

# XPaths from working Automa script
XPATH_MY_APPS      = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[2]/div/div[5]/div[2]'
XPATH_SEARCH_BOX   = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div/div[2]/div[2]/div/div/div/div/div/div/div[5]/div[3]/input'
XPATH_VIEW_FORM    = '//*[@id="root"]/div/div/div/div/div[2]/div[2]/div[2]/div/div[1]/div'
XPATH_PAY_SCHEDULE = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div[2]/div[2]/div[2]/div/div/div/div/div/div/div/div[5]/div[1]/div/div[5]/div[1]/div'
XPATH_BOOK_BTN     = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div[3]/div[2]/div[2]/div/div/div/div/div/div/div/div/div/div[6]/div[1]/div/div'
XPATH_BACK_BTN     = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div[3]/div[2]/div[2]/div/div/div/div/div/div/div/div/div/div[6]/div[3]/div'
PSK_SELECTOR       = '.css-1dbjc4n:nth-child(1) > .r-ry2h4h:nth-child(3)'
PSK_OPTION_POS     = 8


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN  (with automatic double-login fix)
# ─────────────────────────────────────────────────────────────────────────────

async def do_login_once(page: Page):
    """Fill credentials with proper sequencing — ID first, then wait for password field."""
    await page.wait_for_timeout(1000)

    # Step 1 – Fill Login ID
    await page.click('input[data-testid="text-input-outlined"]')
    await page.fill('input[data-testid="text-input-outlined"]', USERNAME)
    print("  Filled Login ID")
    await page.wait_for_timeout(500)

    # Click Continue
    await page.click('.r-q4m81j > .css-901oao')
    print("  Clicked Continue — waiting for password field...")

    # Wait for password field to actually appear before filling
    await page.wait_for_selector(
        '.css-1dbjc4n:nth-child(7) [data-testid="text-input-outlined"]',
        state="visible", timeout=10_000
    )
    await page.wait_for_timeout(500)

    # Step 2 – Fill Password
    await page.fill('.css-1dbjc4n:nth-child(7) [data-testid="text-input-outlined"]', PASSWORD)
    print("  Filled Password — waiting 2s before clicking Login...")

    # 2 second pause before clicking Login
    await page.wait_for_timeout(2000)

    # Click Login
    await page.click('.css-1dbjc4n:nth-child(9) .css-901oao')
    print("  Clicked Login")


async def login(page: Page):
    """Auto-login with proper sequencing. Retries if URL stays on login page."""
    print("\n── LOGIN ─────────────────────────────────────────")
    await page.goto(PRELOGIN_URL, wait_until="domcontentloaded", timeout=30_000)

    attempt = 0
    while True:
        attempt += 1
        print(f"  Login attempt #{attempt} ...")
        await do_login_once(page)

        # Wait up to 30s for URL to leave the login page
        try:
            await page.wait_for_function(
                "!window.location.href.includes('PreLogin') && "
                "!window.location.href.includes('login') && "
                "!window.location.href.includes('Login')",
                timeout=30_000
            )
            print(f"  [✓] Logged in successfully")
            await page.wait_for_timeout(1500)
            return
        except Exception:
            current = page.url
            if "PreLogin" not in current and "login" not in current.lower():
                print("  [✓] Logged in (URL check passed)")
                return
            print("  Still on login page — retrying...")
            await page.goto(PRELOGIN_URL, wait_until="domcontentloaded", timeout=30_000)


# ─────────────────────────────────────────────────────────────────────────────
# SETUP NAVIGATION (one-time, after login)
# ─────────────────────────────────────────────────────────────────────────────

async def navigate_to_app(page: Page):
    print("\n── NAVIGATING TO APPLICATION ─────────────────────")

    async def safe(xpath, name, timeout=8000):
        try:
            loc = page.locator(f'xpath={xpath}')
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.scroll_into_view_if_needed()
            await loc.click()
            print(f"  [✓] {name}")
            return True
        except Exception as e:
            print(f"  [✗] {name}: {e}")
            return False

    await safe(XPATH_MY_APPS, "My Applications")
    await page.wait_for_timeout(1000)

    await safe(XPATH_SEARCH_BOX, "Search Box click")
    await page.wait_for_timeout(400)
    await page.fill(f'xpath={XPATH_SEARCH_BOX}', APP_REF_NO)
    print(f"  Typed ARN: {APP_REF_NO}")
    await page.wait_for_timeout(400)

    # "..." action menu
    await page.click('.css-1dbjc4n:nth-child(9) .css-1dbjc4n:nth-child(2) .css-1dbjc4n:nth-child(7) .css-901oao:nth-child(1)')
    print("  [✓] Action menu (...)")
    await page.wait_for_timeout(800)

    await safe(XPATH_VIEW_FORM, "View Form")
    await page.wait_for_timeout(800)


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACT BEARER TOKEN
# ─────────────────────────────────────────────────────────────────────────────

async def get_bearer_token(page: Page) -> str:
    """
    Navigate to Pay & Schedule + select PSK once to trigger the real API call,
    then capture the Bearer token from that request.
    """
    print("\n── EXTRACTING BEARER TOKEN ───────────────────────")
    token_holder = {"token": None}

    async def on_request(request):
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and token_holder["token"] is None:
            token_holder["token"] = auth.split(" ", 1)[1]
            print(f"  [✓] Bearer token captured ({token_holder['token'][:30]}...)")

    page.on("request", on_request)

    # Click Pay & Schedule
    try:
        loc = page.locator(f'xpath={XPATH_PAY_SCHEDULE}')
        await loc.wait_for(state="visible", timeout=8000)
        await loc.click()
        await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"  [!] Pay & Schedule click: {e}")

    # Select PSK to trigger the showslotsbylocation call
    await _select_psk(page)
    await page.wait_for_timeout(2000)  # wait for API call to fire

    page.remove_listener("request", on_request)

    if not token_holder["token"]:
        print("  [!] Could not auto-capture token — check network tab manually")
        token_holder["token"] = input("  Paste Bearer token here → ").strip()

    return token_holder["token"]


async def get_recaptcha_sitekey(page: Page) -> str:
    """Return the known site key (Enterprise reCAPTCHA, extracted from page source)."""
    print(f"  [✓] Using reCAPTCHA Enterprise site key: {RECAPTCHA_SITEKEY[:20]}...")
    return RECAPTCHA_SITEKEY


# ─────────────────────────────────────────────────────────────────────────────
# PSK SELECTION  (UI, used during setup)
# ─────────────────────────────────────────────────────────────────────────────

async def _select_psk(page: Page):
    try:
        await page.wait_for_selector(PSK_SELECTOR, timeout=5000)
        try:
            await page.select_option(PSK_SELECTOR, index=PSK_OPTION_POS - 1)
            return
        except Exception:
            pass
        await page.click(PSK_SELECTOR)
        await page.wait_for_timeout(400)
        opts = page.locator(f'{PSK_SELECTOR} > *')
        if await opts.count() >= PSK_OPTION_POS:
            await opts.nth(PSK_OPTION_POS - 1).click()
    except Exception as e:
        print(f"  [!] PSK select: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# POLLING LOOP  — intercept-based (browser handles reCAPTCHA naturally)
# Each iteration: click PSK → browser auto-solves reCAPTCHA → API fires →
#                 we capture the response → check dates → click back
# Also writes the latest captcha token to captcha_token.txt for check_slots.sh
# ─────────────────────────────────────────────────────────────────────────────

class RestartNeeded(Exception):
    """Raised when the browser should be closed and a fresh login done."""


async def reset_ip():
    """Renew DHCP lease, print IP before/after, then signal a full browser restart."""
    print("\n  ── IP RESET ─────────────────────────────────────")

    async def get_ip():
        proc = await asyncio.create_subprocess_shell(
            "curl -s --max-time 5 https://api.ipify.org",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await proc.communicate()
        return out.decode().strip() or "unknown"

    ip_before = await get_ip()
    print(f"  Current IP : {ip_before}")

    import platform
    print("  Renewing DHCP lease...")
    if platform.system() == "Windows":
        cmd = "ipconfig /release & ipconfig /renew"
    else:
        cmd = "ipconfig set en0 DHCP"
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()
    await asyncio.sleep(5)

    ip_after = await get_ip()
    print(f"  New IP     : {ip_after}")
    if ip_before == ip_after:
        print("  IP unchanged (ISP kept same address) — restarting browser anyway.")
    else:
        print("  IP changed!")
    print("  Closing browser and logging in fresh...\n")

    raise RestartNeeded()


def _save_token_for_shell(captcha_token: str):
    """Write the latest working reCAPTCHA token to disk for check_slots.sh."""
    try:
        with open("captcha_token.txt", "w") as f:
            f.write(captcha_token)
    except Exception:
        pass


async def fast_poll_loop(page: Page, bearer_token: str, site_key: str):
    print("\n── POLLING LOOP (intercept-based) ────────────────")
    print(f"  Dates wanted : {', '.join(REQUIRED_DATES)}")
    print(f"  Browser handles reCAPTCHA automatically each check.")
    print("  Press Ctrl+C to stop.\n")

    await page.evaluate("window.confirm = () => true; window.alert = () => true;")

    attempt      = 0
    block_streak = 0
    start_time   = time.time()

    while True:
        attempt += 1
        t0 = time.time()

        # Prepare a future to capture the next showslotsbylocation response
        response_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def on_response(response):
            if "showslotsbylocation" in response.url and not response_future.done():
                try:
                    # Also capture the captcha token from the request body
                    try:
                        req_body = response.request.post_data
                        if req_body:
                            body_json = json.loads(req_body)
                            tok = body_json.get("requestResponseMap", {}).get("token", "")
                            if tok:
                                _save_token_for_shell(tok)
                    except Exception:
                        pass
                    data = await response.json()
                    response_future.set_result(data)
                except Exception as exc:
                    if not response_future.done():
                        response_future.set_exception(exc)

        page.on("response", on_response)

        try:
            # If already on ScheduleAppointment page, click Back first
            if "ScheduleAppointment" in page.url:
                back = page.locator(f'xpath={XPATH_BACK_BTN}')
                if await back.count() > 0:
                    await back.click()
                    await page.wait_for_timeout(800)

            # Click Pay & Schedule — navigate to PSK selection page
            pay = page.locator(f'xpath={XPATH_PAY_SCHEDULE}')
            try:
                await pay.wait_for(state="visible", timeout=6000)
                await pay.click()
                await page.wait_for_timeout(600)
            except Exception:
                # Try navigating back to app view if Pay & Schedule still not found
                back = page.locator(f'xpath={XPATH_BACK_BTN}')
                if await back.count() > 0:
                    await back.click()
                    await page.wait_for_timeout(1000)
                else:
                    print(f"[#{attempt}] Pay & Schedule not found — navigating to app...")
                    await navigate_to_app(page)
                    await page.wait_for_timeout(1000)
                page.remove_listener("response", on_response)
                continue

            # Select PSK — this triggers reCAPTCHA + API call automatically
            await _select_psk(page)

            # Wait for the intercepted response
            try:
                data = await asyncio.wait_for(response_future, timeout=20)
            except asyncio.TimeoutError:
                print(f"[#{attempt}] No API response in 20s — skipping")
                page.remove_listener("response", on_response)
                continue

        finally:
            page.remove_listener("response", on_response)

        elapsed_ms = int((time.time() - t0) * 1000)
        total_s    = int(time.time() - start_time)

        rm       = data.get("requestResponseMap", {})
        dates    = rm.get("dates") or []
        earliest = rm.get("earliestApptDate", "—")

        # Dump full raw response to disk every attempt so we can inspect structure
        try:
            with open("slots_result.json", "w") as f:
                json.dump({"raw_rm": rm, "dates": dates, "earliest": earliest,
                           "attempt": attempt, "ms": elapsed_ms}, f, indent=2)
        except Exception:
            pass

        if data.get("strReturnString") == "error":
            errors = data.get("actionErrors", [])
            block_streak += 1
            print(f"[#{attempt}] {elapsed_ms}ms | blocked ({block_streak}) — {'; '.join(errors)}")
            if block_streak >= BLOCK_THRESHOLD:
                block_streak = 0
                await reset_ip()
            continue
        elif dates:
            block_streak = 0

            # If earliestApptDate is a wanted date but not in dates[], log all rm keys
            if earliest in REQUIRED_DATES and earliest not in dates:
                print(f"  [!] earliestApptDate={earliest} is wanted but NOT in dates[] — rm keys: {list(rm.keys())}")
                print(f"  [!] Full rm dump: {json.dumps(rm)[:500]}")

            # Collect all dates from dates[] plus check earliestApptDate directly
            all_dates = set(dates)
            if earliest and earliest != "—":
                all_dates.add(earliest)

            found = next((d for d in REQUIRED_DATES if d in all_dates), None)
            print(f"[#{attempt}] {elapsed_ms}ms | {len(dates)} slots — earliest: {earliest}")
            for d in sorted(dates):
                marker = " ← WANTED" if d in REQUIRED_DATES else ""
                print(f"    {d}{marker}")
            if earliest not in dates and earliest != "—":
                marker = " ← WANTED (earliest)" if earliest in REQUIRED_DATES else " (earliest, not in list)"
                print(f"    {earliest}{marker}")

            if found:
                print(f"\n{'='*54}")
                print(f"  ★★★  WANTED DATE FOUND: {found} — BOOKING NOW  ★★★")
                print(f"{'='*54}")
                for booking_attempt in range(1, 4):  # try up to 3 times
                    booked = await book_via_api(found, bearer_token)
                    if booked:
                        return True
                    print(f"  Booking attempt {booking_attempt}/3 failed — retrying immediately...")
                    await asyncio.sleep(1)
                print("  [✗] All booking attempts failed — continuing to poll")
        else:
            print(f"[#{attempt}] {elapsed_ms}ms | 0 slots ({total_s}s total)")

        # Click Back to return to the app page for next iteration
        back = page.locator(f'xpath={XPATH_BACK_BTN}')
        if await back.count() > 0:
            await back.click()
        await page.wait_for_timeout(400)


async def _refresh_bearer(page: Page) -> str:
    """After re-login, navigate back to get a fresh bearer token."""
    await navigate_to_app(page)
    return await get_bearer_token(page)


# ─────────────────────────────────────────────────────────────────────────────
# BOOKING  — direct API call (fast, no UI clicks needed)
# ─────────────────────────────────────────────────────────────────────────────

async def book_via_api(date: str, bearer_token: str) -> bool:
    import urllib.request
    payload = json.dumps({
        "requestResponseMap": {
            "appRefNo": APP_REF_NO,
            "enquiryQuota": "",
            "appTask": "Schedule",
            "appointmentQuota": "Online",
            "calendarDisplayFlag": "Y",
            "calApptDate": date,
            "pboId": PBO_ID,
        }
    }).encode()
    req = urllib.request.Request(
        "https://api1.passportindia.gov.in/v1/secure/bookappointonline",
        data=payload,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://services1.passportindia.gov.in",
            "Referer": "https://services1.passportindia.gov.in/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "x-aim-plugin-installed": "true",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        print(f"  Booking response: {json.dumps(result)}")
        if result.get("strReturnString") == "error":
            errors = result.get("actionErrors", [])
            print(f"  [✗] API booking failed: {'; '.join(errors)}")
            return False
        b_rm   = result.get("requestResponseMap", {})
        appt_id = b_rm.get("appointmentId") or b_rm.get("apptId") or "—"
        print(f"\n[✓✓] BOOKING COMPLETED via API! Appointment ID: {appt_id}")
        with open("booking_result.json", "w") as f:
            json.dump(result, f, indent=2)
        return True
    except Exception as e:
        print(f"  [✗] API booking error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# BOOKING  (UI fallback — kept for reference)
# ─────────────────────────────────────────────────────────────────────────────

async def book_via_ui(page: Page) -> bool:
    """Click the Book button, handle confirm popup, return True if successful."""
    try:
        book = page.locator(f'xpath={XPATH_BOOK_BTN}')
        await book.wait_for(state="visible", timeout=5000)
        await book.scroll_into_view_if_needed()
        await book.click()
        await page.wait_for_timeout(3000)

        for txt in ["confirm", "ok", "yes", "proceed"]:
            btn = page.locator(f'button:has-text("{txt}")').first
            if await btn.count() > 0:
                print(f"  Confirm popup → '{txt}'")
                await btn.click()
                await page.wait_for_timeout(4000)
                break

        body = (await page.evaluate("document.body.innerText")).lower()
        has_error = any(w in body for w in ["undefined", "not taken an appointment", "error", "failed"])
        if has_error:
            print("  Backend error on booking — retrying once ...")
            for txt in ["close", "ok", "cancel"]:
                btn = page.locator(f'button:has-text("{txt}")').first
                if await btn.count() > 0:
                    await btn.click()
                    break
            await page.wait_for_timeout(2000)
            await book.click()
            await page.wait_for_timeout(3000)
            body = (await page.evaluate("document.body.innerText")).lower()
            if any(w in body for w in ["undefined", "not taken an appointment", "error", "failed"]):
                print("  [✗] Booking failed after retry")
                return False

        print("\n[✓✓] BOOKING COMPLETED!")
        return True

    except Exception as e:
        print(f"  Booking error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def start_session(p):
    """Open browser, login, navigate, and start polling. Raises RestartNeeded on IP reset."""
    browser = await p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        )
    )
    page = await context.new_page()
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    try:
        await login(page)
        await navigate_to_app(page)

        bearer = await get_bearer_token(page)
        site_key = await get_recaptcha_sitekey(page)

        back = page.locator(f'xpath={XPATH_BACK_BTN}')
        if await back.count() > 0:
            await back.click()
            await page.wait_for_timeout(800)

        with open("bearer_token.txt", "w") as f:
            f.write(bearer)
        print(f"\n  Bearer saved to bearer_token.txt")
        print(f"  SiteKey: {site_key}")

        await fast_poll_loop(page, bearer, site_key)

    except RestartNeeded:
        raise
    finally:
        try:
            await browser.close()
            print("  Browser closed.")
        except Exception:
            pass


async def run():
    async with async_playwright() as p:
        session = 0
        while True:
            session += 1
            if session > 1:
                print(f"\n══ SESSION #{session} — fresh browser + login ══\n")
            try:
                await start_session(p)
                break   # Polling finished normally (booking done)
            except RestartNeeded:
                print("  Restarting in 3s...\n")
                await asyncio.sleep(3)
                continue


if __name__ == "__main__":
    asyncio.run(run())
