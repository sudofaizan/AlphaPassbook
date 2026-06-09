#!/usr/bin/env python3
"""
Passport India - v3: Hybrid API mode
- Slots API requires a reCAPTCHA token — read from captcha_token.txt (written by v1/v2)
- Books via direct API call (no browser needed for booking)
- Run v1 or v2 alongside to keep captcha_token.txt fresh, OR paste a token manually

HOW TO USE:
  Option A: Run v1/v2 in parallel — it keeps captcha_token.txt updated automatically
  Option B: Paste a fresh token into captcha_token.txt manually from DevTools

  Either way, set BEARER_TOKEN below and run: python3 check_slots_v3.py
"""

import asyncio
import json
import os
import time
import aiohttp

# ── Configuration ──────────────────────────────────────────────────────────────
# Paste Bearer token from DevTools → Network → any request → Authorization header
BEARER_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJRRUVSMTExMDIwMjIiLCJhdWQiOiJPbmxpbmUtQ2l0aXplbi1BcGkiLCJuYmYiOjE3ODA5MzEyMjAsImlzcyI6Imh0dHBzOi8vd3d3LnBhc3Nwb3J0aW5kaWEuZ292LmluL3BzcCIsInRva2VuX3R5cGUiOiJhY2Nlc3NfdG9rZW4iLCJleHAiOjE3ODA5NDU2MjAsImlhdCI6MTc4MDkzMTIyMCwianRpIjoiODI2NjQxNzg5ODExMjIyMiJ9.WEvFOBossf5H4nCxe6LbNeKsVhW7OJeJ3bd9ckqfK-jqFgtAZ8g1b3Ro9atKrMxlEMGH0-H7oWgu4doDsI9xr8FndXRWy4UFMyizcWQLb7znU-sYH27htmPmJDt2SXl-zyz-jKy-0WW-OXRP3CHArVZQw9g2mYK0rmgwtIvV-N18AR6SVrO6vIfSERcfQB8iIQngYajC2Hk6aznTGIIJDOWcWi3OssfUEhbBfYTAc3jbLTpYn_CGMXNvFMZTYc7dL7BaYvOOEQD7zRAnDCxBEhNcM19fSF8iMCPo0jIpXhl5t2L1h14GMJCS549jGC-iZwyN8ylI1ItKP1Ielat7cA"

APP_REF_NO        = "26-0065296425"
PBO_ID            = "6"
PFC_LOCATION      = 291
APPOINTMENT_QUOTA = "Online"

REQUIRED_DATES = [
    "08/06/2026", "09/06/2026", "10/06/2026",
    "12/06/2026", "13/06/2026", "14/06/2026",
    "15/06/2026", "16/06/2026", "17/06/2026",
    "18/06/2026", "19/06/2026",
]

POLL_INTERVAL_S = 0.3
BLOCK_THRESHOLD = 5
BACKOFF_SECS    = 15
TOKEN_FILE      = "captcha_token.txt"  # written by v1/v2 automatically
# ───────────────────────────────────────────────────────────────────────────────

SLOTS_URL = "https://api1.passportindia.gov.in/v1/secure/showslotsbylocation"
BOOK_URL  = "https://api1.passportindia.gov.in/v1/secure/bookappointonline"


def make_headers(bearer: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://services1.passportindia.gov.in",
        "Referer": "https://services1.passportindia.gov.in/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "x-aim-plugin-installed": "true",
        "Connection": "keep-alive",
    }


def read_captcha_token() -> str:
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


async def check_slots(session: aiohttp.ClientSession, captcha_token: str) -> dict:
    payload = {
        "requestResponseMap": {
            "appRefNo": APP_REF_NO,
            "enquiryQuota": "",
            "isGOESFlag": "N",
            "appTask": "Schedule",
            "appointmentQuota": APPOINTMENT_QUOTA,
            "pfcLocation": PFC_LOCATION,
            "pboId": PBO_ID,
            "token": captcha_token,
        }
    }
    async with session.post(SLOTS_URL, json=payload, headers=make_headers(BEARER_TOKEN)) as resp:
        return await resp.json(content_type=None)


async def book_appointment(session: aiohttp.ClientSession, date: str) -> dict:
    payload = {
        "requestResponseMap": {
            "appRefNo": APP_REF_NO,
            "enquiryQuota": "",
            "appTask": "Schedule",
            "appointmentQuota": APPOINTMENT_QUOTA,
            "calendarDisplayFlag": "Y",
            "calApptDate": date,
            "pboId": PBO_ID,
        }
    }
    async with session.post(BOOK_URL, json=payload, headers=make_headers(BEARER_TOKEN)) as resp:
        return await resp.json(content_type=None)


async def run():
    if BEARER_TOKEN == "PASTE_BEARER_TOKEN_HERE":
        print("ERROR: Set your BEARER_TOKEN at the top of the file first.")
        return

    print("── PASSPORT SLOT CHECKER v3 (hybrid API mode) ───")
    print(f"  App Ref    : {APP_REF_NO}")
    print(f"  Dates      : {', '.join(REQUIRED_DATES)}")
    print(f"  Token file : {TOKEN_FILE}  (kept fresh by v1/v2 running in parallel)")
    print("  Press Ctrl+C to stop.\n")

    attempt      = 0
    block_streak = 0
    start_time   = time.time()
    last_token   = ""

    async with aiohttp.ClientSession() as session:
        while True:
            attempt += 1
            t0 = time.time()

            captcha_token = read_captcha_token()
            if not captcha_token:
                print(f"[#{attempt}] Waiting for captcha token in {TOKEN_FILE} ...")
                await asyncio.sleep(2)
                continue
            if captcha_token != last_token:
                print(f"  [✓] Fresh captcha token loaded ({captcha_token[:20]}...)")
                last_token = captcha_token

            try:
                data = await check_slots(session, captcha_token)
            except Exception as e:
                print(f"[#{attempt}] Request error: {e} — retrying in {BACKOFF_SECS}s")
                await asyncio.sleep(BACKOFF_SECS)
                continue

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
                    print(f"  Too many blocks — backing off {BACKOFF_SECS}s...")
                    await asyncio.sleep(BACKOFF_SECS)
                continue

            # Build full candidate set (dates[] + earliestApptDate)
            all_dates = set(dates)
            if earliest and earliest != "—":
                all_dates.add(earliest)

            block_streak = 0

            if dates:
                found = next((d for d in REQUIRED_DATES if d in all_dates), None)
                print(f"[#{attempt}] {elapsed_ms}ms | {len(dates)} slots — earliest: {earliest}")
                for d in sorted(dates):
                    marker = " ← WANTED" if d in REQUIRED_DATES else ""
                    print(f"    {d}{marker}")
                if earliest not in dates and earliest != "—":
                    marker = " ← WANTED (earliest)" if earliest in REQUIRED_DATES else " (earliest)"
                    print(f"    {earliest}{marker}")

                if found:
                    print(f"\n{'='*54}")
                    print(f"  ★★★  WANTED DATE FOUND: {found} — BOOKING NOW  ★★★")
                    print(f"{'='*54}")

                    for booking_attempt in range(1, 4):
                        try:
                            result = await book_appointment(session, found)
                            print(f"  Booking response: {json.dumps(result)}")

                            b_rm = result.get("requestResponseMap", {})
                            appt_id = b_rm.get("appointmentId") or b_rm.get("apptId") or ""
                            ret = result.get("strReturnString", "")

                            if ret == "error":
                                errors = result.get("actionErrors", [])
                                print(f"  [✗] Booking attempt {booking_attempt}/3 failed: {'; '.join(errors)}")
                                await asyncio.sleep(1)
                                continue

                            print(f"\n[✓✓] BOOKING COMPLETED! Appointment ID: {appt_id}")
                            with open("booking_result.json", "w") as f:
                                json.dump(result, f, indent=2)
                            return

                        except Exception as e:
                            print(f"  [✗] Booking attempt {booking_attempt}/3 error: {e}")
                            await asyncio.sleep(1)

                    print("  [✗] All 3 booking attempts failed — continuing to poll")

            else:
                print(f"[#{attempt}] {elapsed_ms}ms | 0 slots ({total_s}s total)")

            await asyncio.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    asyncio.run(run())
