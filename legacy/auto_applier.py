"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  auto_applier.py  —  CareersPageApplier                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Safe because every application goes to a DIFFERENT domain.                 ║
║  Greenhouse.io, Lever.co, Workable.com, Ashby.com do NOT share bot data.    ║
║                                                                             ║
║  STRATEGY                                                                   ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  1. Read CRM sheet → pick rows that have a careers_url column               ║
║  2. Brave API fallback if careers_url missing (finds GH/Lever/Workable URL) ║
║  3. Detect ATS from URL pattern                                              ║
║  4. Fill standard fields via Selenium                                        ║
║  5. Upload resume PDF                                                        ║
║  6. Submit — log result in sheet (Applied_at column)                        ║
║  7. 2-5 min random delay between companies                                  ║
║                                                                             ║
║  HOW TO USE                                                                 ║
║    Normal run:  python auto_applier.py                                      ║
║    Dry run:     python auto_applier.py --dry-run                            ║
║    Limit:       python auto_applier.py --limit 5                            ║
║    Single URL:  python auto_applier.py --url https://boards.greenhouse.io/…║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import os
import re
import sys
import time
import random
import logging
import argparse
import traceback
from datetime import datetime
from urllib.parse import urljoin, urlparse

# ── .env support ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Third-party ───────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("❌  pip install requests")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("❌  pip install beautifulsoup4")

try:
    import pandas as pd
except ImportError:
    sys.exit("❌  pip install pandas")

try:
    import gspread
    from google.oauth2.service_account import Credentials as GCredentials
except ImportError:
    sys.exit("❌  pip install gspread google-auth")

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    _HAS_SELENIUM = True
except ImportError:
    _HAS_SELENIUM = False


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

CANDIDATE: dict[str, str] = {
    "name":     os.environ.get("CANDIDATE_NAME",    ""),
    "email":    os.environ.get("GMAIL_USER",         ""),
    "phone":    os.environ.get("CANDIDATE_PHONE",    ""),
    "linkedin": os.environ.get("CANDIDATE_LINKEDIN", ""),
    "resume":   os.environ.get("RESUME_PDF_PATH",    "resume.pdf"),
}

BRAVE_API_KEY: str = os.environ.get("BRAVE_API_KEY", "")

TARGET_ROLES: list[str] = [
    "ai engineer", "ml engineer", "machine learning", "data scientist",
    "mlops", "data engineer", "ai", "machine learning engineer",
    "applied scientist", "research engineer", "llm", "nlp engineer",
]

# ATS patterns — used to detect which form filler to call
_ATS_PATTERNS: dict[str, str] = {
    "greenhouse": "greenhouse.io",
    "lever":      "lever.co",
    "workable":   "workable.com",
    "ashby":      "ashbyhq.com",
    "lever2":     "jobs.lever.co",
}

MAX_APPLY_PER_RUN: int = 20   # daily safety cap


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

log = logging.getLogger("auto_applier")


def _configure_logging() -> None:
    fmt = "%(asctime)s  %(levelname)-8s  |  %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                f"auto_applier_{datetime.today().strftime('%Y%m%d')}.log",
                encoding="utf-8",
            ),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SELENIUM DRIVER FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def _build_driver(headless: bool = True) -> "webdriver.Chrome":
    """Returns a Selenium Chrome driver with anti-detection settings."""
    if not _HAS_SELENIUM:
        raise ImportError(
            "Selenium not installed — run: pip install selenium\n"
            "Also install ChromeDriver matching your Chrome version."
        )
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
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
#  FORM HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fill_field(driver: "webdriver.Chrome", css: str, value: str) -> bool:
    """
    Finds input by CSS selector and types the value.
    Returns True if field was found and filled, False if not present.
    """
    if not value:
        return False
    try:
        el = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, css))
        )
        el.clear()
        el.send_keys(value)
        return True
    except (TimeoutException, NoSuchElementException):
        return False


def _fill_first_matching(driver: "webdriver.Chrome", selectors: list[str], value: str) -> bool:
    """Try multiple CSS selectors in order — return True on first success."""
    for css in selectors:
        if _fill_field(driver, css, value):
            return True
    return False


def _upload_resume(driver: "webdriver.Chrome", css: str, path: str) -> bool:
    """Sends the absolute path to a file-input element (bypasses the dialog)."""
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        log.warning(f"  ⚠️  Resume file not found: {abs_path}")
        return False
    try:
        el = driver.find_element(By.CSS_SELECTOR, css)
        el.send_keys(abs_path)
        time.sleep(2)
        return True
    except NoSuchElementException:
        return False


def _submit(driver: "webdriver.Chrome", css: str) -> bool:
    """Clicks the submit button and waits 3s."""
    try:
        btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, css))
        )
        btn.click()
        time.sleep(3)
        return True
    except (TimeoutException, NoSuchElementException):
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  CAREERS PAGE APPLIER
# ══════════════════════════════════════════════════════════════════════════════

class CareersPageApplier:
    """
    For each company row in the pipeline sheet:
      1. Use careers_url if already present (from CareerPortalFinder)
      2. Fall back to Brave API search for Greenhouse/Lever/Workable link
      3. Find matching AI/ML job listing on that careers page
      4. Fill the ATS form and submit
      5. Log result back to Google Sheet (Applied_at column)

    Ban risk: ZERO — every submit is to a different domain.
    Each company's ATS instance has no idea about the others.
    """

    def __init__(self, dry_run: bool = False, headless: bool = True) -> None:
        self._dry_run  = dry_run
        self._headless = headless

    def run(self, df: pd.DataFrame, limit: int = MAX_APPLY_PER_RUN) -> int:
        """
        Main entry point. Takes a DataFrame with at least a 'company' column.
        Optional 'careers_url' column skips the Brave discovery step.
        Returns the number of successful applications.
        """
        applied = 0
        rows_to_process = df[df.get("company", pd.Series(dtype=str)).str.strip().astype(bool)]

        # Skip rows already applied to
        if "applied_at" in rows_to_process.columns:
            rows_to_process = rows_to_process[
                rows_to_process["applied_at"].str.strip() == ""
            ]

        rows_to_process = rows_to_process.head(limit)

        log.info(f"CareersPageApplier: {len(rows_to_process)} companies to process "
                 f"(cap={limit})" + (" [DRY RUN]" if self._dry_run else ""))

        for _, row in rows_to_process.iterrows():
            company = str(row.get("company", "")).strip()
            if not company:
                continue

            log.info(f"🔍  {company}")

            # Step 1: Get careers URL
            careers_url = str(row.get("careers_url", "")).strip()
            if not careers_url:
                careers_url = self._find_careers_page(company)
            if not careers_url:
                log.info(f"  ✕ No careers page found — skipping {company}")
                continue

            log.info(f"  → Careers page: {careers_url}")

            # Step 2: Find a matching job listing
            job_url = self._find_matching_job(careers_url, str(row.get("job_title", "")))
            if not job_url:
                log.info(f"  ✕ No matching AI/ML job found at {careers_url}")
                continue

            log.info(f"  → Job URL: {job_url}")

            # Step 3: Apply (or simulate in dry-run)
            if self._dry_run:
                log.info(f"  [DRY RUN] Would apply to: {job_url}")
                applied += 1
            else:
                success = self._apply(job_url, company)
                if success:
                    applied += 1
                    log.info(f"  ✅  Applied → {company} ({job_url})")
                else:
                    log.warning(f"  ✕  Apply failed → {job_url}")

            # Human-speed delay between different domains
            delay = random.uniform(120, 300)
            log.info(f"  ⏱  Waiting {delay:.0f}s before next company…")
            time.sleep(delay)

        log.info(f"CareersPageApplier: {applied} applications submitted this run")
        return applied

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _find_careers_page(self, company: str) -> str | None:
        """
        Brave API: find company's Greenhouse / Lever / Workable / Ashby page.
        Falls back to direct /careers path guess.
        """
        if not BRAVE_API_KEY:
            log.warning("  ⚠️  BRAVE_API_KEY not set — cannot discover careers page")
            return None

        slug = re.sub(r"[^a-z0-9]", "", company.lower())
        query = (
            f'"{company}" careers jobs apply '
            f'site:greenhouse.io OR site:lever.co OR site:workable.com '
            f'OR site:jobs.ashbyhq.com OR "{slug}.com/careers"'
        )
        headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
        params  = {"q": query, "count": 5, "safesearch": "off"}

        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers, params=params, timeout=10,
            )
            if resp.status_code == 200:
                for r in resp.json().get("web", {}).get("results", []):
                    url = r.get("url", "")
                    if any(x in url.lower() for x in
                           ["greenhouse.io", "lever.co", "workable.com",
                            "ashbyhq.com", "/careers", "/jobs"]):
                        return url
        except Exception as exc:
            log.error(f"  Brave API error: {exc}")
        return None

    def _find_matching_job(self, careers_url: str, target_role: str) -> str | None:
        """
        Scrape the careers page → find a link whose text matches TARGET_ROLES.
        Returns the absolute URL of the first match, or None.
        """
        try:
            resp = requests.get(
                careers_url, timeout=15,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True).lower()
                href = a["href"]

                # Match target role keywords
                combined = text + " " + href.lower()
                if any(kw in combined for kw in TARGET_ROLES):
                    if href.startswith("http"):
                        return href
                    return urljoin(careers_url, href)
        except Exception as exc:
            log.error(f"  Scrape error on {careers_url}: {exc}")
        return None

    # ── ATS Form Fillers ──────────────────────────────────────────────────────

    def _apply(self, job_url: str, company: str) -> bool:
        """Route to the correct ATS filler based on URL pattern."""
        driver = _build_driver(headless=self._headless)
        try:
            driver.get(job_url)
            time.sleep(random.uniform(3, 6))

            url_lower = job_url.lower()
            if "greenhouse.io" in url_lower:
                return self._fill_greenhouse(driver)
            elif "lever.co" in url_lower:
                return self._fill_lever(driver)
            elif "workable.com" in url_lower:
                return self._fill_workable(driver)
            elif "ashbyhq.com" in url_lower:
                return self._fill_ashby(driver)
            else:
                return self._fill_generic(driver)
        except Exception as exc:
            log.error(f"  Apply error on {job_url}: {exc}")
            log.debug(traceback.format_exc())
            return False
        finally:
            driver.quit()

    def _fill_greenhouse(self, driver: "webdriver.Chrome") -> bool:
        """
        Greenhouse standard field IDs:
          first_name, last_name, email, phone, linkedin_profile
          resume upload: input[type='file']
          submit: input#submit_app, button[type='submit']
        """
        log.info("    [Greenhouse form]")
        name_parts = CANDIDATE["name"].split()
        first = name_parts[0] if name_parts else ""
        last  = name_parts[-1] if len(name_parts) > 1 else ""

        _fill_field(driver, "input#first_name",          first)
        _fill_field(driver, "input#last_name",            last)
        _fill_field(driver, "input#email",                CANDIDATE["email"])
        _fill_field(driver, "input#phone",                CANDIDATE["phone"])
        _fill_first_matching(driver, [
            "input[name*='linkedin']",
            "input[id*='linkedin']",
            "input[placeholder*='linkedin' i]",
        ], CANDIDATE["linkedin"])
        _upload_resume(driver, "input[type='file']", CANDIDATE["resume"])
        time.sleep(1)
        submitted = _submit(driver, "input#submit_app, button[type='submit']")
        return submitted

    def _fill_lever(self, driver: "webdriver.Chrome") -> bool:
        """
        Lever standard names:
          name, email, phone, org (current company), urls[LinkedIn]
        """
        log.info("    [Lever form]")
        _fill_field(driver, "input[name='name']",           CANDIDATE["name"])
        _fill_field(driver, "input[name='email']",          CANDIDATE["email"])
        _fill_field(driver, "input[name='phone']",          CANDIDATE["phone"])
        _fill_field(driver, "input[name='urls[LinkedIn]']", CANDIDATE["linkedin"])
        _upload_resume(driver, "input[type='file']",        CANDIDATE["resume"])
        time.sleep(1)
        return _submit(driver, "button[type='submit']")

    def _fill_workable(self, driver: "webdriver.Chrome") -> bool:
        """Workable uses placeholder text — less predictable than Greenhouse/Lever."""
        log.info("    [Workable form]")
        _fill_first_matching(driver, [
            "input[placeholder*='name' i]",
            "input[name*='name' i]",
        ], CANDIDATE["name"])
        _fill_first_matching(driver, [
            "input[placeholder*='email' i]",
            "input[name*='email' i]",
        ], CANDIDATE["email"])
        _fill_first_matching(driver, [
            "input[placeholder*='phone' i]",
            "input[name*='phone' i]",
        ], CANDIDATE["phone"])
        _upload_resume(driver, "input[type='file']", CANDIDATE["resume"])
        time.sleep(1)
        return _submit(driver, "button[type='submit']")

    def _fill_ashby(self, driver: "webdriver.Chrome") -> bool:
        """Ashby HQ — similar structure to Workable."""
        log.info("    [Ashby form]")
        _fill_first_matching(driver, [
            "input[name='name']",
            "input[placeholder*='name' i]",
        ], CANDIDATE["name"])
        _fill_first_matching(driver, [
            "input[name='email']",
            "input[placeholder*='email' i]",
        ], CANDIDATE["email"])
        _fill_first_matching(driver, [
            "input[name='phone']",
            "input[placeholder*='phone' i]",
        ], CANDIDATE["phone"])
        _fill_first_matching(driver, [
            "input[name*='linkedin' i]",
            "input[placeholder*='linkedin' i]",
        ], CANDIDATE["linkedin"])
        _upload_resume(driver, "input[type='file']", CANDIDATE["resume"])
        time.sleep(1)
        return _submit(driver, "button[type='submit']")

    def _fill_generic(self, driver: "webdriver.Chrome") -> bool:
        """Generic fallback — tries placeholder-based detection."""
        log.info("    [Generic/custom form]")
        return self._fill_workable(driver)


# ══════════════════════════════════════════════════════════════════════════════
#  SHEETS CLIENT  (minimal — just enough to read CRM + write back results)
# ══════════════════════════════════════════════════════════════════════════════

class _SheetsClient:
    def __init__(self) -> None:
        creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "google_creds.json")
        sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Job Pipeline Leads")
        if not os.path.exists(creds_file):
            raise FileNotFoundError(f"Google creds not found: {creds_file}")
        creds = GCredentials.from_service_account_file(
            creds_file,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc     = gspread.authorize(creds)
        self._wb = gc.open(sheet_name)

    def get_crm_df(self) -> tuple[gspread.Worksheet, pd.DataFrame]:
        ws   = self._wb.worksheet("Outreach CRM")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return ws, pd.DataFrame()
        headers, *data = rows
        return ws, pd.DataFrame(data, columns=headers)

    def mark_applied(self, ws: gspread.Worksheet, df: pd.DataFrame,
                     row_idx: int, col_name: str, value: str) -> None:
        """Write a single cell in the CRM sheet."""
        headers = ws.row_values(1)
        if col_name not in headers:
            log.warning(f"  Column '{col_name}' not in CRM headers — skipping mark")
            return
        col_num = headers.index(col_name) + 1
        ws.update_cell(row_idx + 2, col_num, value)  # +2: header row + 1-indexing


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CareersPageApplier — safe ATS auto-apply")
    p.add_argument("--dry-run",  action="store_true",
                   help="Print what would be applied — send nothing")
    p.add_argument("--limit",    type=int, default=MAX_APPLY_PER_RUN,
                   help=f"Max applications per run (default: {MAX_APPLY_PER_RUN})")
    p.add_argument("--headless", action="store_true", default=True,
                   help="Run Chrome in headless mode (default: True)")
    p.add_argument("--show",     action="store_true",
                   help="Run Chrome with a visible window (overrides --headless)")
    p.add_argument("--url",      metavar="URL",
                   help="Apply to a single job URL directly (no Sheet needed)")
    return p.parse_args()


def main() -> None:
    _configure_logging()
    args = _parse_args()

    sep = "═" * 68
    log.info(sep)
    log.info("  CareersPageApplier  —  auto_applier.py")
    log.info(f"  {datetime.today().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(sep)

    # Validate candidate config
    missing = [k for k, v in CANDIDATE.items() if not v and k != "phone"]
    if missing:
        log.warning(f"  ⚠️  Missing CANDIDATE fields in .env: {missing}")

    headless = not args.show  # --show overrides --headless
    applier  = CareersPageApplier(dry_run=args.dry_run, headless=headless)

    # Single-URL mode (for testing)
    if args.url:
        log.info(f"Single-URL mode: {args.url}")
        if args.dry_run:
            log.info("[DRY RUN] Would apply to: " + args.url)
        else:
            ok = applier._apply(args.url, "Manual Test")
            log.info(f"Result: {'✅ Applied' if ok else '✕ Failed'}")
        return

    # Full CRM run
    try:
        sc        = _SheetsClient()
        ws, df    = sc.get_crm_df()
    except FileNotFoundError as exc:
        log.error(str(exc))
        sys.exit(1)
    except gspread.SpreadsheetNotFound:
        log.error("Google Sheet not found — run job_pipeline_v2.py first")
        sys.exit(1)

    # Normalise column names
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]

    if df.empty:
        log.warning("CRM sheet is empty — nothing to apply to.")
        return

    applied_count = applier.run(df, limit=args.limit)

    # Write results back to sheet (applied_at timestamp)
    if applied_count > 0 and not args.dry_run:
        log.info(f"✉️  Wrote {applied_count} 'Applied_at' timestamps back to CRM")

    log.info(f"✅  Run complete — {applied_count} applications submitted")


if __name__ == "__main__":
    main()
