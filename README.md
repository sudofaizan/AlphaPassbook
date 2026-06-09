# Passport Appointment Slot Checker
### Automatic slot finder & booker for Passport Seva portal

---

## What this does

This program:
- Opens a browser automatically
- Logs into the Passport Seva website with your details
- Keeps checking for available appointment dates every few seconds
- When it finds a date you want → **books it automatically**
- Shows a popup notification on your screen when a date is found

---

## STEP 1 — Install Python

1. Open this link in your browser:
   **https://www.python.org/downloads/**

2. Click the big yellow **"Download Python"** button

3. Open the downloaded file to start installation

4. ⚠️ **VERY IMPORTANT** — On the first screen of the installer:
   - Check the box that says **"Add Python to PATH"**
   - Then click **"Install Now"**

5. Wait for it to finish. Click **Close**.

---

## STEP 2 — Open Command Prompt

1. Press the **Windows key** on your keyboard
2. Type **cmd**
3. Click **Command Prompt** (the black icon)
4. A black window will open — this is where you type commands

---

## STEP 3 — Install Required Packages

In the black Command Prompt window, type each line below and press **Enter** after each one.

Wait for each one to finish before typing the next:

```
pip install playwright
```

```
playwright install chromium
```

You will see a lot of text appearing — that is normal. Wait until it stops and shows a blinking cursor again.

---

## STEP 4 — Edit the Script with Your Details

1. Find the file **check_slots.py** (it was sent to you)
2. Right-click on it → click **"Open with"** → click **"Notepad"**
3. At the top of the file, find these lines and change them:

```python
USERNAME   = "QEER11102022"       ← Change to YOUR Login ID
PASSWORD   = "Pass@1235"          ← Change to YOUR Password
APP_REF_NO = "26-0065296425"      ← Change to YOUR Application Reference Number
```

**Your Application Reference Number** looks like: `26-XXXXXXXXXX`
(You can find it on your passport application confirmation email)

4. Find the **REQUIRED_DATES** section and add the dates you want:

```python
REQUIRED_DATES  = [
    "08/06/2026",
    "09/06/2026",
    "10/06/2026",
]
```

Change these dates to the ones you want. Format must be **DD/MM/YYYY**.

5. Press **Ctrl + S** to save the file. Close Notepad.

---

## STEP 5 — Run the Script

### Option A — Easy way (double-click)
1. Right-click on **check_slots.py**
2. Click **"Open with"**
3. Click **"Python"**

### Option B — From Command Prompt
1. Open Command Prompt (see Step 2)
2. Type this command and press Enter:

```
cd Desktop
```
*(If the file is not on Desktop, replace Desktop with the folder name)*

3. Then type:

```
python check_slots.py
```

---

## STEP 6 — What Happens Next

1. A browser window will open automatically
2. The script fills in your Login ID and clicks Continue
3. Then fills in your Password and clicks Login
4. After login, it navigates to your application automatically
5. It starts checking for available dates — you will see messages like:

```
[#1] 2100ms | 0 slots
[#2] 2050ms | 0 slots
[#3] 2200ms | 5 slots — earliest: 27/08/2026
```

6. When a date you want becomes available:
   - A notification popup appears on your screen
   - The script **automatically books the appointment**
   - You will see: `BOOKING COMPLETED!`

---

## STEP 7 — Important Things to Know

| Situation | What happens |
|---|---|
| Script asks for Login ID / Password | Already filled automatically |
| "0 slots" showing | No dates available yet — keep waiting |
| "blocked" showing | Normal — script resets and tries again |
| Browser closes and reopens | Normal — script refreshed the connection |
| `BOOKING COMPLETED!` | Done! Check your email for confirmation |

---

## If Something Goes Wrong

### "pip is not recognized"
- You forgot to check **"Add Python to PATH"** during install
- Uninstall Python and install again — remember to check that box

### "No module named playwright"
- Run this command again in Command Prompt:
  ```
  pip install playwright
  ```

### Script stops with a red error
- Close the Command Prompt window
- Run the script again from Step 5

### Browser opens but login fails
- Check your Username and Password in the script (Step 4)
- Make sure there are no extra spaces

---

## To Stop the Script

Click on the Command Prompt black window and press **Ctrl + C**

---

## Files in this folder

| File | What it is |
|---|---|
| `check_slots.py` | The main script — **this is what you run** |
| `bearer_token.txt` | Created automatically — do not delete |
| `captcha_token.txt` | Created automatically — do not delete |
| `slots_result.json` | Created automatically — shows latest check result |

---

*For help, contact the person who sent you this script.*
