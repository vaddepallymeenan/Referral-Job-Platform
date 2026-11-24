"""
naukri_updater.py — Daily Naukri profile micro-edit.

Toggles a trailing period in your resume headline so Naukri treats
the profile as "recently updated" and boosts it in recruiter searches.

Strategy:
  • Logs in with your Naukri credentials (stored in .env)
  • Opens the Profile edit page
  • Toggles period at end of headline: "Foo" → "Foo." → "Foo" → …
  • Saves and exits

CRON SETUP (run once — paste this and press Enter):
  (crontab -l 2>/dev/null; echo "0 8 * * * cd . && python naukri_updater.py >> logs/naukri_updater.log 2>&1") | crontab -

Required .env keys:
  NAUKRI_EMAIL    — your Naukri login email
  NAUKRI_PASSWORD — your Naukri login password

Ban risk: MINIMAL — one edit/day to YOUR profile is perfectly normal user behaviour.
"""

from __future__ import annotations

import os
import sys
import time
import random
import logging
from datetime import datetime

# ── .env support ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Selenium ──────────────────────────────────────────────────────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from selenium.webdriver.chrome.options import Options as ChromeOptions
except ImportError:
    sys.exit("❌  pip install selenium")


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

NAUKRI_EMAIL:    str = os.environ.get("NAUKRI_EMAIL",    "")
NAUKRI_PASSWORD: str = os.environ.get("NAUKRI_PASSWORD", "")

_LOGIN_URL   = "https://www.naukri.com/nlogin/login"
_PROFILE_URL = "https://www.naukri.com/mnjuser/profile"

log = logging.getLogger("naukri_updater")


# ══════════════════════════════════════════════════════════════════════════════
#  DRIVER FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def _build_driver() -> webdriver.Chrome:
    opts = ChromeOptions()
    # Run with a visible window so login CAPTCHA (if any) can be solved manually
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Use your real Brave profile so existing Naukri session is already logged in
    brave_profile = os.environ.get("BRAVE_PROFILE_PATH", "")
    if brave_profile and os.path.exists(brave_profile):
        opts.add_argument(f"--user-data-dir={os.path.dirname(brave_profile)}")
        opts.add_argument(f"--profile-directory={os.path.basename(brave_profile)}")

    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


# ══════════════════════════════════════════════════════════════════════════════
#  CORE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def _login(driver: webdriver.Chrome) -> bool:
    """
    Logs into Naukri. Returns True if login succeeded.
    Skips login if the Brave profile is already authenticated.
    """
    driver.get(_LOGIN_URL)
    time.sleep(random.uniform(3, 5))

    # Check if already logged in (profile page loads without redirect)
    if "nlogin" not in driver.current_url:
        log.info("  Already logged in via Brave profile session")
        return True

    if not NAUKRI_EMAIL or not NAUKRI_PASSWORD:
        log.error(
            "❌  NAUKRI_EMAIL and NAUKRI_PASSWORD not set in .env — "
            "cannot log in. Set them or log in manually in Brave first."
        )
        return False

    try:
        email_field = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[type='text'], input[name*='email' i], #usernameField")
            )
        )
        email_field.clear()
        email_field.send_keys(NAUKRI_EMAIL)
        time.sleep(random.uniform(0.5, 1.2))

        pwd_field = driver.find_element(
            By.CSS_SELECTOR, "input[type='password'], #passwordField"
        )
        pwd_field.clear()
        pwd_field.send_keys(NAUKRI_PASSWORD)
        time.sleep(random.uniform(0.5, 1.0))

        login_btn = driver.find_element(
            By.CSS_SELECTOR, "button[type='submit'], .loginButton, input[type='submit']"
        )
        login_btn.click()
        time.sleep(random.uniform(3, 5))

        if "nlogin" in driver.current_url:
            log.error("❌  Login failed — check NAUKRI_EMAIL / NAUKRI_PASSWORD in .env")
            return False

        log.info("✅  Logged into Naukri")
        return True

    except (TimeoutException, NoSuchElementException) as exc:
        log.error(f"❌  Login error: {exc}")
        return False


def update_naukri_profile() -> bool:
    """
    Opens Naukri profile edit page and toggles a trailing period in
    the resume headline, triggering a "recently updated" signal.
    Returns True if the update succeeded.
    """
    driver = _build_driver()
    try:
        if not _login(driver):
            return False

        driver.get(_PROFILE_URL)
        time.sleep(random.uniform(4, 7))

        # Locate the headline field (Naukri uses several different selectors)
        headline_selectors = [
            "input[placeholder*='headline' i]",
            "textarea[placeholder*='headline' i]",
            "input[name*='headline' i]",
            "#resumeHeadline",
            ".headline-edit input",
        ]

        headline_el = None
        for sel in headline_selectors:
            try:
                headline_el = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                break
            except TimeoutException:
                continue

        if not headline_el:
            log.error("❌  Could not find headline field — Naukri may have changed its layout")
            return False

        current = (headline_el.get_attribute("value") or headline_el.text or "").strip()
        log.info(f"  Current headline: {current!r}")

        # Toggle trailing period
        new_val = current.rstrip(".") if current.endswith(".") else current + "."
        log.info(f"  New headline:     {new_val!r}")

        headline_el.clear()
        time.sleep(0.3)
        headline_el.send_keys(new_val)
        time.sleep(random.uniform(1, 2))

        # Click Save
        save_selectors = [
            "button[type='submit']",
            "button.saveBtn",
            "button.save",
            "input[type='submit']",
            ".save-button",
        ]
        saved = False
        for sel in save_selectors:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                btn.click()
                time.sleep(2)
                saved = True
                break
            except (TimeoutException, NoSuchElementException):
                continue

        if not saved:
            log.error("❌  Could not find save button")
            return False

        log.info(f"✅  Naukri headline updated: {current!r} → {new_val!r}")
        return True

    except Exception as exc:
        log.error(f"❌  Naukri update failed: {exc}")
        return False
    finally:
        driver.quit()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _configure_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  |  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                f"logs/naukri_updater_{datetime.today().strftime('%Y%m%d')}.log",
                encoding="utf-8",
            ),
        ],
    )


if __name__ == "__main__":
    _configure_logging()
    log.info("━━━━  Naukri Profile Updater  ━━━━")
    ok = update_naukri_profile()
    if not ok:
        log.warning("  Update may not have succeeded — check logs/naukri_updater_*.log")
    sys.exit(0 if ok else 1)
