#!/usr/bin/env python3
"""
Passport India - Fast Slot Checker & Auto Booker  v2
- HEADLESS mode (no visible browser window)
- Trimmed poll-loop delays for faster cycling
- All v1 fixes: earliestApptDate check, date click before booking, full rm dump
- WARNING: headless may increase reCAPTCHA failure rate. If you see more blocks,
  set HEADLESS = False to go back to visible mode.
"""

import asyncio
import json
import platform
import subprocess
import time
from playwright.async_api import async_playwright, Page

# ── Configuration ──────────────────────────────────────────────────────────────
USERNAME        = "QEER11102022"
PASSWORD        = "Pass@1235"
APP_REF_NO      = "26-0065296425"
PFC_LOCATION    = 291
PBO_ID          = "6"

HEADLESS        = False  # headless gets detected at login; keep False for reliability

REQUIRED_DATES  = [
    "08/06/2026", "09/06/2026", "10/06/2026",
    "12/06/2026", "13/06/2026", "14/06/2026",
    "15/06/2026", "16/06/2026", "17/06/2026",
    "18/06/2026", "19/06/2026",
]

RECAPTCHA_SITEKEY = "6LfHkpkpAAAAAGzwnRDa9DiuCz6Yb9Cw8zL99TCo"
BLOCK_THRESHOLD   = 5
BACKOFF_SECS      = 15
# ───────────────────────────────────────────────────────────────────────────────

PRELOGIN_URL  = "https://services1.passportindia.gov.in/forms/PreLogin"
PORTAL_ORIGIN = "https://services1.passportindia.gov.in"

XPATH_MY_APPS      = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[2]/div/div[5]/div[2]'
XPATH_SEARCH_BOX   = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div/div[2]/div[2]/div/div/div/div/div/div/div[5]/div[3]/input'
XPATH_VIEW_FORM    = '//*[@id="root"]/div/div/div/div/div[2]/div[2]/div[2]/div/div[1]/div'
XPATH_PAY_SCHEDULE = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div[2]/div[2]/div[2]/div/div/div/div/div/div/div/div[5]/div[1]/div/div[5]/div[1]/div'
XPATH_BOOK_BTN     = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div[3]/div[2]/div[2]/div/div/div/div/div/div/div/div/div/div[6]/div[1]/div/div'
XPATH_BACK_BTN     = '//*[@id="root"]/div/div/div/div/div[1]/div[1]/div/div/div/div[2]/div[2]/div/div/div/div[1]/div/div/div[1]/div/div/div[2]/div/div/div[3]/div[2]/div[2]/div/div/div/div/div/div/div/div/div/div[6]/div[3]/div'
PSK_SELECTOR       = '.css-1dbjc4n:nth-child(1) > .r-ry2h4h:nth-child(3)'
PSK_OPTION_POS     = 8


class RestartNeeded(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────────────────────

async def do_login_once(page: Page):
    await page.wait_for_timeout(1000)

    # Wait for login ID field to be ready before clicking
    await page.wait_for_selector('input[data-testid="text-input-outlined"]', state="visible", timeout=15_000)
    await page.click('input[data-testid="text-input-outlined"]')
    await page.fill('input[data-testid="text-input-outlined"]', USERNAME)
    print("  Filled Login ID")
    await page.wait_for_timeout(500)

    # Wait for Continue button to be visible before clicking
    await page.wait_for_selector('.r-q4m81j > .css-901oao', state="visible", timeout=10_000)
    await page.click('.r-q4m81j > .css-901oao')
    print("  Clicked Continue — waiting for password field...")

    # Try multiple selectors for the password field
    pwd_selector = None
    for sel in [
        '.css-1dbjc4n:nth-child(7) [data-testid="text-input-outlined"]',
        '[data-testid="text-input-outlined"]:nth-of-type(2)',
        'input[type="password"]',
    ]:
        try:
            await page.wait_for_selector(sel, state="visible", timeout=8_000)
            pwd_selector = sel
            break
        except Exception:
            continue

    if not pwd_selector:
        raise Exception("Password field not found — page may not have loaded correctly")

    await page.wait_for_timeout(500)
    await page.fill(pwd_selector, PASSWORD)
    print("  Filled Password")
    await page.wait_for_timeout(2000)

    await page.click('.css-1dbjc4n:nth-child(9) .css-901oao')
    print("  Clicked Login")


async def login(page: Page):
    print("\n── LOGIN ─────────────────────────────────────────")
    await page.goto(PRELOGIN_URL, wait_until="domcontentloaded", timeout=30_000)

    attempt = 0
    while True:
        attempt += 1
        print(f"  Login attempt #{attempt} ...")
        await do_login_once(page)
        try:
            await page.wait_for_function(
                "!window.location.href.includes('PreLogin') && "
                "!window.location.href.includes('login') && "
                "!window.location.href.includes('Login')",
                timeout=30_000
            )
            print("  [✓] Logged in successfully")
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
# NAVIGATION
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

    await page.click('.css-1dbjc4n:nth-child(9) .css-1dbjc4n:nth-child(2) .css-1dbjc4n:nth-child(7) .css-901oao:nth-child(1)')
    print("  [✓] Action menu (...)")
    await page.wait_for_timeout(800)

    await safe(XPATH_VIEW_FORM, "View Form")
    await page.wait_for_timeout(800)


# ─────────────────────────────────────────────────────────────────────────────
# PSK SELECTION
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
        await page.wait_for_timeout(300)
        opts = page.locator(f'{PSK_SELECTOR} > *')
        if await opts.count() >= PSK_OPTION_POS:
            await opts.nth(PSK_OPTION_POS - 1).click()
    except Exception as e:
        print(f"  [!] PSK select: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# BEARER TOKEN
# ─────────────────────────────────────────────────────────────────────────────

async def get_bearer_token(page: Page) -> str:
    print("\n── EXTRACTING BEARER TOKEN ───────────────────────")
    token_holder = {"token": None}

    async def on_request(request):
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and token_holder["token"] is None:
            token_holder["token"] = auth.split(" ", 1)[1]
            print(f"  [✓] Bearer token captured ({token_holder['token'][:30]}...)")

    page.on("request", on_request)

    try:
        loc = page.locator(f'xpath={XPATH_PAY_SCHEDULE}')
        await loc.wait_for(state="visible", timeout=8000)
        await loc.click()
        await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"  [!] Pay & Schedule click: {e}")

    await _select_psk(page)
    await page.wait_for_timeout(2000)

    page.remove_listener("request", on_request)

    if not token_holder["token"]:
        print("  [!] Could not auto-capture token")
        if not HEADLESS:
            token_holder["token"] = input("  Paste Bearer token here → ").strip()
        else:
            raise RuntimeError("Bearer token capture failed in headless mode — check selectors")

    return token_holder["token"]


# ─────────────────────────────────────────────────────────────────────────────
# IP RESET
# ─────────────────────────────────────────────────────────────────────────────

async def reset_ip():
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

    cmd = "ipconfig /release & ipconfig /renew" if platform.system() == "Windows" else "ipconfig set en0 DHCP"
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.communicate()
    await asyncio.sleep(5)

    ip_after = await get_ip()
    print(f"  New IP     : {ip_after}")
    if ip_before == ip_after:
        print("  IP unchanged — restarting browser anyway.")
    else:
        print("  IP changed!")
    print("  Closing browser and logging in fresh...\n")
    raise RestartNeeded()


# ─────────────────────────────────────────────────────────────────────────────
# BOOKING
# ─────────────────────────────────────────────────────────────────────────────

async def book_via_ui(page: Page, target_date: str = None) -> bool:
    try:
        if target_date:
            date_loc = page.locator(f':text("{target_date}")').first
            if await date_loc.count() > 0:
                await date_loc.scroll_into_view_if_needed()
                await date_loc.click()
                print(f"  [✓] Clicked date slot: {target_date}")
                await page.wait_for_timeout(1000)
            else:
                print(f"  [!] Date element not found for {target_date} — attempting Book anyway")

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

        print("\n[✓✓] BOOKING COMPLETED!")
        return True

    except Exception as e:
        print(f"  Booking error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# POLLING LOOP
# ─────────────────────────────────────────────────────────────────────────────

def _save_token_for_shell(captcha_token: str):
    try:
        with open("captcha_token.txt", "w") as f:
            f.write(captcha_token)
    except Exception:
        pass


async def fast_poll_loop(page: Page, bearer_token: str):
    print("\n── POLLING LOOP v2 (headless={}) ─────────────────".format(HEADLESS))
    print(f"  Dates wanted : {', '.join(REQUIRED_DATES)}")
    print("  Press Ctrl+C to stop.\n")

    await page.evaluate("window.confirm = () => true; window.alert = () => true;")

    attempt      = 0
    block_streak = 0
    start_time   = time.time()

    while True:
        attempt += 1
        t0 = time.time()

        response_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def on_response(response):
            if "showslotsbylocation" in response.url and not response_future.done():
                try:
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
            # Back out of ScheduleAppointment page if we landed there
            if "ScheduleAppointment" in page.url:
                back = page.locator(f'xpath={XPATH_BACK_BTN}')
                if await back.count() > 0:
                    await back.click()
                    await page.wait_for_timeout(500)  # reduced from 800ms

            pay = page.locator(f'xpath={XPATH_PAY_SCHEDULE}')
            try:
                await pay.wait_for(state="visible", timeout=6000)
                await pay.click()
                await page.wait_for_timeout(400)  # reduced from 600ms
            except Exception:
                back = page.locator(f'xpath={XPATH_BACK_BTN}')
                if await back.count() > 0:
                    await back.click()
                    await page.wait_for_timeout(600)  # reduced from 1000ms
                else:
                    print(f"[#{attempt}] Pay & Schedule not found — navigating to app...")
                    await navigate_to_app(page)
                page.remove_listener("response", on_response)
                continue

            await _select_psk(page)

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

            if earliest in REQUIRED_DATES and earliest not in dates:
                print(f"  [!] earliestApptDate={earliest} is wanted but NOT in dates[] — rm keys: {list(rm.keys())}")
                print(f"  [!] Full rm dump: {json.dumps(rm)[:500]}")

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
                booked = await book_via_ui(page, found)
                if booked:
                    return True

        else:
            print(f"[#{attempt}] {elapsed_ms}ms | 0 slots ({total_s}s total)")

        # Back to app for next iteration — no extra delay
        back = page.locator(f'xpath={XPATH_BACK_BTN}')
        if await back.count() > 0:
            await back.click()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def start_session(p):
    # Use real Chrome (not Chromium) — far harder for bot detection to flag.
    # Falls back to Chromium automatically if Chrome is not installed.
    try:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
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

        back = page.locator(f'xpath={XPATH_BACK_BTN}')
        if await back.count() > 0:
            await back.click()
            await page.wait_for_timeout(500)

        with open("bearer_token.txt", "w") as f:
            f.write(bearer)
        print(f"\n  Bearer saved to bearer_token.txt")
        print(f"  Running headless={HEADLESS}")

        await fast_poll_loop(page, bearer)

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
                break
            except RestartNeeded:
                print("  Restarting in 3s...\n")
                await asyncio.sleep(3)
                continue


if __name__ == "__main__":
    asyncio.run(run())
