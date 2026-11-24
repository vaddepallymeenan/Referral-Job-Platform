"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       Startup Opportunity Discovery Engine  —  v4  (India-Focused)          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  WHAT CHANGED FROM v3                                                        ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  P2  CONTACTS_PER_COMPANY 4 → 2  (LinkedIn cap: 30 invites/week, not 100)  ║
║  P3  MAX_COMPANIES_TO_ENRICH = 40  (cap + sort by freshness before enrich) ║
║  P4  SeenCompaniesCache — 14-day cross-run dedup in existing SQLite DB      ║
║  P5  Relevance pre-filter — skip companies with zero AI/ML keywords         ║
║  P6  ProductHuntSource → YourStorySource  (Indian startups, not US apps)   ║
║  P7  FundingSource scrapes YourStory + Inc42 instead of TechCrunch          ║
║  P8  IITKAlumniSource — 8 fixed Brave queries → "IITK Alumni" sheet tab    ║
║                                                                             ║
║  EVERYTHING FROM v3 IS PRESERVED:                                            ║
║    Wellfound · YC · Brave Search · Scorer (+3 IITK bonus) · QueryCache      ║
║    Google Sheets writer · SQLite cache · _build_queries() strategy           ║
║                                                                             ║
║  Run  python job_pipeline_v2.py --setup   to regenerate .env template      ║
║  Run  python job_pipeline_v2.py           for a normal weekly run           ║
║  Run  python job_pipeline_v2.py --sources wellfound,yc   to limit sources  ║
╚══════════════════════════════════════════════════════════════════════════════╝

WHY THIS FINDS BETTER OPPORTUNITIES THAN v3
──────────────────────────────────────────
  YourStory covers Indian AI/ML startups specifically.
  Inc42 covers Indian funding rounds religiously (Series A/B seed).
  TechCrunch was US-heavy and rarely mentioned Indian funding.
  ProductHunt was mostly US consumer apps with zero India hiring relevance.

  The IITK Alumni module runs 8 standalone Brave queries (32 queries/month)
  and surfaces IITK alumni in AI roles across all Indian startups — these
  contacts respond at 60–70% vs 10–15% for cold recruiter outreach.
"""

from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────────
import os
import re
import sys
import json
import time
import random
import hashlib
import logging
import sqlite3
import argparse
import textwrap
import traceback
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode
from typing import TypedDict, Optional, Protocol, Any
from urllib.parse import urlsplit, urlunsplit, urljoin

# ── Load .env FIRST so os.environ is populated before Config reads it ─────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Third-party ───────────────────────────────────────────────────────────────
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.exit("❌  pip install requests")

try:
    import pandas as pd
except ImportError:
    sys.exit("❌  pip install pandas")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("❌  pip install beautifulsoup4")

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        NoSuchElementException,
        StaleElementReferenceException,
        WebDriverException,
    )
except ImportError:
    sys.exit("❌  pip install undetected-chromedriver selenium")

try:
    import gspread
    from google.oauth2.service_account import Credentials as GCredentials
except ImportError:
    sys.exit("❌  pip install gspread google-auth")


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PipelineConfig:
    """
    Single source of truth for all pipeline constants.
    Run `python job_pipeline_v2.py --setup` to generate a .env template.
    """

    # ── Credentials ───────────────────────────────────────────────────────────
    BRAVE_API_KEY:           str  = os.environ.get("BRAVE_API_KEY",           "")
    HUNTER_API_KEY:          str  = os.environ.get("HUNTER_API_KEY",          "")
    GOOGLE_CREDENTIALS_FILE: str  = os.environ.get("GOOGLE_CREDENTIALS_FILE", "google_creds.json")
    GOOGLE_SHEET_NAME:       str  = os.environ.get("GOOGLE_SHEET_NAME",       "Job Pipeline Leads")
    BRAVE_PROFILE_PATH:      str  = os.environ.get("BRAVE_PROFILE_PATH",      "")

    # ── Source toggles (override via --sources CLI flag) ──────────────────────
    # Comma-separated list of sources to run. "all" runs everything.
    # Example: ACTIVE_SOURCES=wellfound,yc  (skip YourStory and Funding)
    ACTIVE_SOURCES: str = os.environ.get("ACTIVE_SOURCES", "all")

    # ── Wellfound scraper (unchanged from v2) ─────────────────────────────────
    WELLFOUND_URL: str = (
        "https://wellfound.com/jobs"
        "?role=ai-engineer&role=machine-learning-engineer&role=mlops-engineer"
        "&role=data-scientist&role=data-analyst&role=data-engineer"
        "&salary_min=800000&salary_max=1500000"
        "&yoe_max=3"
        # Indian tech hubs — Wellfound uses city-level location slugs.
        # Priority order: Bangalore first (biggest AI hub), then Hyd, Mumbai, Pune, Remote.
        "&location[]=Bengaluru%2C+Karnataka%2C+India"
        "&location[]=Hyderabad%2C+Telangana%2C+India"
        "&location[]=Mumbai%2C+Maharashtra%2C+India"
        "&location[]=Pune%2C+Maharashtra%2C+India"
        "&location[]=Remote"
        # Sort newest first so each daily run sees fresh jobs, not the same page
        "&order=recently_posted"
    )
    WELLFOUND_MAX_PAGES:      int   = 3
    WELLFOUND_SCROLL_PX:      int   = 4000
    WELLFOUND_PAGE_TIMEOUT_S: int   = 15

    # ── YC Source ─────────────────────────────────────────────────────────────
    YC_MAX_PAGES:       int   = 3
    YC_REQUEST_DELAY_S: float = 2.5

    # ── YourStory Source (replaces ProductHunt — P6) ──────────────────────────
    # Scrape YourStory company listings: Indian startups actively building.
    YS_MAX_PAGES: int = 2

    # ── Funding Source ────────────────────────────────────────────────────────
    # YourStory + Inc42 cover Indian funding. TechCrunch is US-heavy.
    FUNDING_MAX_PAGES: int = 2

    # ── Enricher / Brave Search ────────────────────────────────────────────────
    CSE_RESULTS_PER_QUERY:    int   = 5
    CONTACTS_PER_COMPANY:     int   = 2    # P2: was 4; LinkedIn cap means 1-2 max anyway
    API_DELAY_S:              float = 1.5
    MAX_RETRIES:              int   = 3
    BACKOFF_BASE_S:           float = 2.0

    # ── Enrichment cap (P3) ────────────────────────────────────────────────────
    # Enrich only the freshest N companies per run. Saves Brave quota.
    # 40 companies x 3 queries = 120 queries/run x 4 runs/month = 480 queries/month.
    MAX_COMPANIES_TO_ENRICH:  int   = 40

    # ── Cache (unchanged from v2) ─────────────────────────────────────────────
    CACHE_DB_PATH:            str   = "pipeline_cache.db"
    CACHE_TTL_DAYS:           int   = 7

    # ── Scorer (unchanged from v2) ────────────────────────────────────────────
    MIN_RELEVANCE_SCORE:      int   = 2
    MAX_NAME_LENGTH:          int   = 25

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = (
        "DEBUG" if os.environ.get("PIPELINE_DEBUG", "").strip() == "1" else "INFO"
    )

    # ── Anti-detection timing ─────────────────────────────────────────────────
    DELAY_MIN_S:    float = 2.5
    DELAY_MAX_S:    float = 7.8
    SCROLL_STEP_PX: int   = 220

    # ── HTTP headers for requests-based scrapers ──────────────────────────────
    REQUEST_HEADERS: dict = None  # type: ignore  # set below via __post_init__ workaround

    def __post_init__(self) -> None:
        object.__setattr__(self, "REQUEST_HEADERS", {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })


CFG = PipelineConfig()


# ── Dynamic Company Targeting Criteria (P10 / Fix 2) ────────────────────────
TARGET_COMPANY_CRITERIA = {
    "employee_range": (10, 200),      # Widened: captures Series B teams still founder-accessible
    "stages": ["Seed", "Series A", "Series B", "Pre-Series A", "Pre-Seed", "Angel"],  # Added Series B
    "founded_after": 2018,            # Widened: avoids blocking good 2018-2019 companies
    "locations": ["Bengaluru", "Hyderabad", "Mumbai", "Pune", "Delhi", "Gurgaon", "Noida", "Chennai", "Kolkata"],
    "must_have_tech": ["AI", "ML", "LLM", "GenAI", "Data", "NLP", "RAG", "Deep Learning", "Vision", "Intelligence"],
    "funding_range_usd_m": (0.5, 10.0)  # Widened: matches FundingSource's $10M hard cap
}



# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class Company(TypedDict, total=False):
    """
    The primary unit.  Every source produces Company objects.

    hiring_signal values:
      "job_post"  — company was found because it posted a job (Wellfound)
      "yc_batch"  — company is in a recent YC batch
      "launch"    — company recently launched / listed on YourStory (building)
      "funding"   — company recently received funding (about to hire)
    """
    name:          str
    source:        str    # "wellfound" | "yc" | "yourstory" | "funding"
    source_url:    str
    discovered_at: str
    hiring_signal: str
    job_title:     str
    urgency:       str
    company_description: str


class Contact(TypedDict, total=False):
    source_company:  str
    contact_name:    str
    contact_title:   str
    linkedin_url:    str
    relevance_score: int
    email:           str


class FinalRow(TypedDict):
    company:         str
    job_title:       str
    urgency:         str
    source:          str
    hiring_signal:   str
    contact_name:    str
    contact_title:   str
    linkedin_url:    str
    relevance_score: int
    date_added:      str
    status:          str


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def _configure_logging() -> logging.Logger:
    numeric_level = getattr(logging, CFG.LOG_LEVEL.upper(), logging.INFO)
    fmt = "%(asctime)s  %(levelname)-8s  %(name)-28s  |  %(message)s"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric_level)
    console.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    log_filename = f"pipeline_{datetime.today().strftime('%Y%m%d_%H%M')}.log"
    file_h = logging.FileHandler(log_filename, encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    root.addHandler(console)
    root.addHandler(file_h)

    for lib in ("urllib3", "gspread", "googleapiclient", "selenium", "undetected_chromedriver"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    logger = logging.getLogger("pipeline")
    logger.info(f"Logging initialised  (console={CFG.LOG_LEVEL}, file=DEBUG → {log_filename})")
    return logger


LOG = _configure_logging()


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _human_delay(lo: float = CFG.DELAY_MIN_S, hi: float = CFG.DELAY_MAX_S) -> None:
    t = random.uniform(lo, hi)
    LOG.debug(f"  ⏱  sleeping {t:.2f}s")
    time.sleep(t)


def _smooth_scroll(driver: uc.Chrome, total_px: int = CFG.WELLFOUND_SCROLL_PX) -> None:
    scrolled = 0
    while scrolled < total_px:
        step = random.randint(CFG.SCROLL_STEP_PX - 40, CFG.SCROLL_STEP_PX + 60)
        driver.execute_script(f"window.scrollBy(0, {step});")
        scrolled += step
        time.sleep(random.uniform(0.35, 0.95))


def _safe_text(root, by: str, css: str, default: str = "") -> str:
    try:
        return root.find_element(by, css).text.strip()
    except (NoSuchElementException, StaleElementReferenceException):
        return default


def _safe_attr(root, by: str, css: str, attr: str = "href", default: str = "") -> str:
    try:
        return root.find_element(by, css).get_attribute(attr) or default
    except (NoSuchElementException, StaleElementReferenceException):
        return default


def _strip_tracking(url: str) -> str:
    if not url:
        return url
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _requests_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(CFG.REQUEST_HEADERS)
    return session


def _today_str() -> str:
    return datetime.today().strftime("%Y-%m-%d")


def _make_yc_driver() -> uc.Chrome:
    """
    Lightweight Brave driver for public sites that don't need a logged-in profile.
    YC is public — we only need a real browser so the page's own JavaScript can
    call the Algolia API (server-side requests get 403 "Host not in allowlist").
    Much faster startup than WellfoundSource._build_driver() — no profile cloning.
    """
    import shutil as _shutil
    import subprocess as _sp
    import tempfile

    log = logging.getLogger("pipeline.yc_driver")

    # ── Find Brave binary ──────────────────────────────────────────────────────
    brave_path = (
        _shutil.which("brave-browser-beta")
        or _shutil.which("brave-browser")
        or _shutil.which("brave")
    )
    if not brave_path:
        for p in [
            "/usr/bin/brave-browser-beta",
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
            "/opt/brave.com/brave/brave",
            os.path.expanduser("~/.local/bin/brave"),
        ]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                brave_path = p
                break

    if not brave_path:
        raise FileNotFoundError(
            "Brave browser binary not found. Install brave-browser or brave-browser-beta."
        )

    brave_version = None
    try:
        result = _sp.run([brave_path, "--version"], capture_output=True, text=True, timeout=5)
        m = re.search(r"(\d+)\.\d+", result.stdout)
        if m:
            brave_version = int(m.group(1))
    except Exception:
        pass

    tmp_root = tempfile.mkdtemp(prefix="brave_yc_")

    opts = uc.ChromeOptions()
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument(f"--user-data-dir={tmp_root}")
    opts.add_argument("--profile-directory=Default")

    try:
        driver = uc.Chrome(
            options=opts,
            use_subprocess=True,
            browser_executable_path=brave_path,
            **({"version_main": brave_version} if brave_version else {}),
        )
    except Exception as exc:
        import shutil as _sh_clean
        _sh_clean.rmtree(tmp_root, ignore_errors=True)
        raise exc

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    driver._yc_tmp_profile = tmp_root  # type: ignore[attr-defined]
    log.info(f"  🌐  YC browser launched (fresh profile, no login needed)")
    return driver


# ══════════════════════════════════════════════════════════════════════════════
#  COMPANY NORMALIZATION LAYER
# ══════════════════════════════════════════════════════════════════════════════

_SUFFIX_PATTERN = re.compile(
    r"(?i)\b(inc|llc|ltd|pvt|private|corporation|corp|"
    r"technologies|technology|tech|labs|lab|solutions|"
    r"ventures|venture|group|hq|io|co)\.?\b",
)


def normalize_company_name(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name)
    name = _SUFFIX_PATTERN.sub("", name)
    name = re.sub(r"[.,:;\-_/]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.lower()


def deduplicate_companies(companies: list[Company]) -> list[Company]:
    source_priority = {"wellfound": 0, "yc": 1, "yourstory": 2, "funding": 3}
    companies_sorted = sorted(
        companies,
        key=lambda c: source_priority.get(c["source"], 9)
    )

    seen: dict[str, Company] = {}
    for company in companies_sorted:
        key = normalize_company_name(company["name"])
        if key and key not in seen:
            seen[key] = company

    return list(seen.values())


def _is_valid_company_name(name: str) -> bool:
    name_lower = name.lower().strip()
    blacklist = {
        "india", "indian", "bengaluru", "bangalore", "mumbai", "delhi", "tech", "ai", "ml",
        "how", "why", "what", "this", "inside", "exclusive", "funding", "exclusive:",
        "here", "meet", "why", "who", "with", "this", "these", "that", "where", "when",
        "january", "february", "march", "april", "may", "june", "july", "august", "september",
        "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday", "today", "yesterday", "tomorrow", "startup", "company",
        "platform", "funding", "series", "seed", "capital",
        "million", "based", "raises", "crore", "raised", "firm", "secures", "closes", "bags",
        "partners", "announces", "gets"
    }
    
    # Direct match check against blacklist
    if name_lower in blacklist:
        return False
        
    # Check if all constituent words are standalone blacklist noise words
    # e.g., "Based Startup" has words ["based", "startup"] which are both blacklisted
    words = name_lower.split()
    if words and all(w in blacklist for w in words):
        return False
        
    if len(name) < 2 or len(name) > 30:
        return False
    if name.isdigit():
        return False
    return True


def _extract_company_from_headline(text: str) -> str | None:
    if not text:
        return None

    # Clean text
    text = re.sub(r"(?i)^(exclusive|funding|news|spotted|just\s+in|update|breakout|story|tech|startup\s+focus):\s*", "", text).strip()
    text = text.replace("“", "").replace("”", "").replace('"', '').replace("'", "")

    # 1. Look for: "based startup [Company] raises" or similar
    based_pattern = r"(?i)based\s+(?:AI\s+)?(?:startup|platform|company|firm)\s+([A-Z][a-zA-Z0-9\s\.\-&]{2,30}?)\s+(?:raises|raised|secures|secured|closes|closed|unveils|unveiled|launches|launched|bags|bagged|gets|got|partners|partnered|announces|announced|funding|to\s+raise)"
    m = re.search(based_pattern, text)
    if m:
        name = m.group(1).strip()
        if _is_valid_company_name(name):
            return name

    # 2. Look for: "[Company] raises/secures/closes/unveils/launches/bags/gets/partners/announces..." at start of headline
    verb_pattern = r"(?i)^([A-Z][a-zA-Z0-9\s\.\-&]{2,30}?)\s+(?:raises|raised|secures|secured|closes|closed|unveils|unveiled|launches|launched|bags|bagged|gets|got|partners|partnered|announces|announced|to\s+raise|funding)\b"
    m = re.search(verb_pattern, text)
    if m:
        name = m.group(1).strip()
        if _is_valid_company_name(name):
            return name

    # 3. Look for: "AI startup [Company] raises..."
    prefix_pattern = r"(?i)^(?:AI\s+)?(?:startup|platform|company)\s+([A-Z][a-zA-Z0-9\s\.\-&]{2,30}?)\s+(?:raises|raised|secures|secured|closes|closed|unveils|unveiled|launches|launched|bags|bagged|gets|got|partners|partnered|announces|announced|funding|to\s+raise)"
    m = re.search(prefix_pattern, text)
    if m:
        name = m.group(1).strip()
        if _is_valid_company_name(name):
            return name

    # 4. Check for capitalized word sequence before "Raises", "Secures" inside the title
    in_title_pattern = r"\b([A-Z][a-zA-Z0-9\s\.\-&]{2,30}?)\s+(?:Raises|Secures|Closes|Unveils|Launches|Bags|Partners|Announces)\b"
    m = re.search(in_title_pattern, text)
    if m:
        name = m.group(1).strip()
        if _is_valid_company_name(name):
            return name

    return None


def _extract_company_from_slug_or_headline(title: str, link: str) -> str | None:
    """
    Extracts the company name from the URL slug as the primary signal.
    Falls back to headline regex if slug extraction fails.
    """
    if not link:
        return _extract_company_from_headline(title)

    try:
        # Extract from URL slug first
        slug = link.rstrip('/').split('/')[-1]
        
        # Remove noise keywords from slug string
        noise_keywords = [
            'raises-funding', 'gets-funding', 'raises', 'funding', 'series', 'seed', 
            'million', 'crore', 'startup', 'launches', 'india', 'ai', 'based',
            'bengaluru', 'bangalore', 'hyderabad', 'mumbai', 'pune', 'delhi',
            'gurgaon', 'gurugram', 'noida', 'chennai', 'tech', 'platform', 
            'company', 'firm', 'secures', 'closes', 'bags', 'partners', 'announces', 'exclusive'
        ]
        
        for noise in noise_keywords:
            slug = slug.replace(f'-{noise}', '').replace(f'{noise}-', '')

        # Convert slug to proper capitalized name
        candidate = ' '.join(w.capitalize() for w in slug.split('-') if len(w) > 2)
        
        if _is_valid_company_name(candidate):
            return candidate
    except Exception:
        pass

    # Fall back to existing regex only if URL parsing fails
    return _extract_company_from_headline(title)


def parse_funding_info(title: str, description: str) -> tuple[float | None, str | None, str | None]:
    """
    Parses funding amount (in USD millions), stage, and location from title and description.
    Returns (funding_amount_in_usd_m, stage, location).
    """
    text = (title + " " + description).lower()
    
    # 1. Parse funding amount
    # Matches: $X million, $X million, X million dollars, $X M, $X.Y M
    # Also matches Indian Rupees: Rs X crore, X cr, X crore
    amount_m = None
    
    # USD matches
    usd_match = re.search(r"\$\s*(\d+(?:\.\d+)?)\s*(million|m|billion|b)?\b", text)
    if usd_match:
        try:
            val = float(usd_match.group(1))
            unit = usd_match.group(2)
            if unit in ("million", "m"):
                amount_m = val
            elif unit in ("billion", "b"):
                amount_m = val * 1000.0
            else:
                if val < 50.0: 
                    amount_m = val
                else:
                    amount_m = val / 1000000.0
        except ValueError:
            pass
    
    # INR matches (1 Crore = ~0.12 Million USD)
    if not amount_m:
        inr_match = re.search(r"(?:rs|inr|rupees)?\s*(\d+(?:\.\d+)?)\s*(?:crore|cr)\b", text)
        if inr_match:
            try:
                val = float(inr_match.group(1))
                amount_m = val * 0.12
            except ValueError:
                pass
            
    # 2. Parse stage
    stage = None
    if "pre-seed" in text or "pre seed" in text:
        stage = "Pre-Seed"
    elif "pre-series a" in text or "pre series a" in text:
        stage = "Pre-Series A"
    elif "series a" in text:
        stage = "Series A"
    elif "series b" in text:
        stage = "Series B"
    elif "series c" in text:
        stage = "Series C"
    elif "seed" in text:
        stage = "Seed"
    elif "angel" in text:
        stage = "Angel"

    # 3. Parse location
    location = None
    indian_cities = ["bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "delhi", "gurgaon", "gurugram", "noida", "chennai"]
    for city in indian_cities:
        if city in text:
            location = city.capitalize()
            if location in ("Bangalore", "Gurugram"):
                if location == "Bangalore":
                    location = "Bengaluru"
                else:
                    location = "Gurgaon"
            break
            
    return amount_m, stage, location



# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE PROTOCOL
# ══════════════════════════════════════════════════════════════════════════════

class StartupSource(Protocol):
    def fetch_companies(self) -> list[Company]:
        ...


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 1 — WELLFOUND  (DO NOT TOUCH — unchanged from v3)
# ══════════════════════════════════════════════════════════════════════════════

class WellfoundSource:
    """
    Scrapes Wellfound job listings with Selenium (clone-profile approach).
    hiring_signal is always "job_post".
    """

    _log = logging.getLogger("pipeline.WellfoundSource")

    _CARD_SELECTORS: list[str] = [
        "[data-test='StartupResult']",
        "[class*='JobListing']",
        ".styles_component__Ey28k",
        "div[class*='styles_component']",
    ]
    _NEXT_SELECTORS: list[str] = [
        "a[rel='next']",
        "button[aria-label='Next page']",
        "[data-test='next-page']",
        "a[data-test='pagination-next']",
    ]
    _TIME_SELECTORS: list[str] = [
        "[class*='posted_']",
        "span[class*='time']",
        ".styles_component__y_mB0",
        "time",
        "[class*='timeAgo']",
    ]

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 1/4 : Wellfound  ━━━━")
        driver = self._build_driver()
        raw_companies: list[Company] = []

        try:
            driver.get(CFG.WELLFOUND_URL)
            _human_delay(3.5, 6.0)

            prev_count = 0
            stale_rounds = 0
            MAX_STALE = 2
            MAX_ROUNDS = CFG.WELLFOUND_MAX_PAGES * 3

            for round_num in range(1, MAX_ROUNDS + 1):
                try:
                    WebDriverWait(driver, CFG.WELLFOUND_PAGE_TIMEOUT_S).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, ", ".join(self._CARD_SELECTORS[:2]))
                        )
                    )
                except TimeoutException:
                    self._log.warning(f"  Round {round_num}: cards never appeared — stopping.")
                    break

                _human_delay(1.0, 2.0)
                page_companies = self._parse_page(driver)
                raw_companies.extend(page_companies)

                current_count = len(raw_companies)
                new_this_round = current_count - prev_count
                self._log.info(
                    f"  📄  Round {round_num}: +{new_this_round} companies "
                    f"(total so far: {current_count})"
                )

                if new_this_round == 0:
                    stale_rounds += 1
                    if stale_rounds >= MAX_STALE:
                        self._log.info("  End of Wellfound results (no new cards after scroll).")
                        break
                else:
                    stale_rounds = 0

                prev_count = current_count
                _smooth_scroll(driver, total_px=CFG.WELLFOUND_SCROLL_PX)
                _human_delay(2.0, 4.0)

        except WebDriverException as exc:
            self._log.error(f"Fatal WebDriver error: {exc}")
        finally:
            driver.quit()
            self._log.debug("  Browser closed.")
            tmp = getattr(driver, "_auto_tmp_profile", None)
            if tmp and os.path.isdir(tmp):
                import shutil as _shutil_cleanup
                try:
                    _shutil_cleanup.rmtree(tmp)
                    self._log.debug(f"  Temp profile cleaned up: {tmp}")
                except Exception:
                    pass

        seen: set[tuple[str, str]] = set()
        unique: list[Company] = []
        for c in raw_companies:
            key = (c["name"].lower(), c["job_title"].lower())
            if key not in seen and c["name"]:
                seen.add(key)
                unique.append(c)

        # Cap results to the freshest 15 discovered companies to keep it highly focused (ROI constraint)
        unique = unique[:15]

        # Self-healing fallback if Wellfound scraper fails / gets blocked by monthly bot protection updates
        if len(unique) == 0:
            self._log.critical(
                "🚨🚨🚨 [CRITICAL] Wellfound scraping yielded 0 results! The scraper has likely been blocked by bot protection or a page layout update."
            )
            self._log.info("  ➔ Triggering automated self-healing Brave Search fallback to discover active Indian startups...")
            fallback_cos = self._run_brave_fallback()
            unique.extend(fallback_cos)

        self._log.info(f"✅  Wellfound complete — {len(unique)} unique companies")
        return unique

    def _run_brave_fallback(self) -> list[Company]:
        if not CFG.BRAVE_API_KEY:
            self._log.warning("  Cannot run Brave fallback: BRAVE_API_KEY not configured in environment.")
            return []
            
        self._log.info("  🔍 Running Brave Search fallback query for active Indian hiring startups...")
        headers = {"Accept": "application/json", "X-Subscription-Token": CFG.BRAVE_API_KEY}
        # Query for Indian startups recently funded/launching that are actively hiring
        q = 'site:yourstory.com OR site:inc42.com "raises" ("seed" OR "series a") India "startup" 2026'
        params = {"q": q, "count": 10}
        
        companies = []
        try:
            resp = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("web", {}).get("results", [])
                for r in results:
                    title = r.get("title", "")
                    url = r.get("url", "")
                    # Extract clean company name
                    name = _extract_company_from_slug_or_headline(title, url)
                    if name and _is_valid_company_name(name):
                        companies.append(Company(
                            name=name,
                            source="wellfound_fallback",
                            source_url=url,
                            discovered_at=_today_str(),
                            hiring_signal="launch",
                            job_title="Active Hiring Startup (Fallback)",
                            urgency="High (Scraper Fallback)",
                            company_description=title,
                        ))
                self._log.info(f"  🚀 Brave Search fallback successfully discovered {len(companies)} alternative startups!")
            else:
                self._log.error(f"  Brave API fallback request returned status code: {resp.status_code}")
        except Exception as e:
            self._log.error(f"  ❌ Brave Search fallback failed: {e}")
            
        return companies

    def _build_driver(self) -> uc.Chrome:
        return _build_shared_driver(self._log)

    def _parse_page(self, driver: uc.Chrome) -> list[Company]:
        cards: list = []
        for sel in self._CARD_SELECTORS:
            try:
                cards = driver.find_elements(By.CSS_SELECTOR, sel)
                if cards:
                    self._log.debug(f"  Cards matched via: {sel!r}")
                    break
            except Exception:
                continue

        if not cards:
            self._log.warning("  ⚠  Zero cards found — Wellfound markup may have changed.")
            return []

        companies: list[Company] = []
        for card in cards:
            try:
                name = (
                    _safe_text(card, By.CSS_SELECTOR, "[data-test='startup-link']")
                    or _safe_text(card, By.CSS_SELECTOR, "h2")
                    or _safe_text(card, By.CSS_SELECTOR, "[class*='startupName']")
                )
                job_title = (
                    _safe_text(card, By.CSS_SELECTOR, "[data-test='role-link']")
                    or _safe_text(card, By.CSS_SELECTOR, "h3")
                    or _safe_text(card, By.CSS_SELECTOR, "a[class*='JobListing']")
                )
                time_text = "Actively hiring"
                for tsel in self._TIME_SELECTORS:
                    candidate = _safe_text(card, By.CSS_SELECTOR, tsel)
                    if candidate:
                        time_text = candidate
                        break

                tagline = (
                    _safe_text(card, By.CSS_SELECTOR, "[class*='tagline']")
                    or _safe_text(card, By.CSS_SELECTOR, "[class*='pitch']")
                    or _safe_text(card, By.CSS_SELECTOR, "[class*='description']")
                    or ""
                ).strip()

                if name.strip():
                    companies.append(Company(
                        name=name.strip(),
                        source="wellfound",
                        source_url=CFG.WELLFOUND_URL,
                        discovered_at=_today_str(),
                        hiring_signal="job_post",
                        job_title=job_title.strip(),
                        urgency=categorize_urgency(time_text),
                        company_description=tagline,
                    ))
            except Exception as exc:
                self._log.debug(f"  Card parse error (skipping): {exc}")

        return companies

    def _click_next(self, driver: uc.Chrome) -> bool:
        for sel in self._NEXT_SELECTORS:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                _human_delay(0.8, 1.5)
                btn.click()
                _human_delay()
                return True
            except (NoSuchElementException, WebDriverException):
                continue
        return False

def _build_shared_driver(log: logging.Logger) -> uc.Chrome:
    import shutil
    import subprocess
    import tempfile

    home = os.path.expanduser("~")

    source_profile: str | None = None

    if CFG.BRAVE_PROFILE_PATH:
        p = os.path.expanduser(CFG.BRAVE_PROFILE_PATH)
        if os.path.isdir(p):
            source_profile = p
            log.info(f"  📂  Using manual Brave profile: {p}")

    if not source_profile:
        candidates = [
            os.path.join(home, ".config", "BraveSoftware", "Brave-Browser-Beta"),
            os.path.join(home, ".config", "BraveSoftware", "Brave-Browser"),
            os.path.join(home, ".config", "brave-browser"),
            os.path.join(home, ".var", "app", "com.brave.Browser", "config", "BraveSoftware", "Brave-Browser"),
        ]
        for brave_base in candidates:
            if not os.path.isdir(brave_base):
                continue
            for sub in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
                p = os.path.join(brave_base, sub)
                if os.path.isdir(p) and os.path.isfile(os.path.join(p, "Cookies")):
                    source_profile = p
                    break
            if source_profile:
                break

    AUTH_FILES = ["Cookies", "Local State", "Preferences", "Login Data"]

    tmp_root    = tempfile.mkdtemp(prefix="brave_auto_")
    tmp_default = os.path.join(tmp_root, "Default")
    os.makedirs(tmp_default, exist_ok=True)

    if source_profile:
        import shutil as _shutil
        import sqlite3 as _sqlite3
        copied = []
        for fname in AUTH_FILES:
            src = os.path.join(source_profile, fname)
            dst_dir = tmp_root if fname == "Local State" else tmp_default
            dst = os.path.join(dst_dir, fname)
            if not os.path.exists(src):
                continue
            try:
                if fname == "Cookies":
                    try:
                        src_conn = _sqlite3.connect(f"file:{src}?mode=ro", uri=True)
                        dst_conn = _sqlite3.connect(dst)
                        src_conn.backup(dst_conn)
                        src_conn.close()
                        dst_conn.close()
                        copied.append("Cookies (safe SQLite backup)")
                    except Exception as e:
                        log.debug(f"  SQLite backup of Cookies failed: {e} — trying plain copy")
                        try:
                            _shutil.copy2(src, dst)
                            copied.append("Cookies (plain copy)")
                        except Exception:
                            pass
                else:
                    _shutil.copy2(src, dst)
                    copied.append(fname)
            except Exception:
                pass
        log.info(
            f"  🍪  Cloned auth files into temp profile: {copied} "
            f"(your real Brave is untouched)"
        )
    else:
        log.warning(
            "  ⚠  Could not find Brave profile — launching with blank profile."
        )

    opts = uc.ChromeOptions()
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument(f"--user-data-dir={tmp_root}")
    opts.add_argument("--profile-directory=Default")

    brave_path = (
        shutil.which("brave-browser-beta")
        or shutil.which("brave-browser")
        or shutil.which("brave")
    )
    if not brave_path:
        extra_paths = [
            "/usr/bin/brave-browser-beta",
            "/usr/bin/brave-browser",
            "/usr/bin/brave",
            "/opt/brave.com/brave/brave",
            os.path.expanduser("~/.local/bin/brave"),
        ]
        for p in extra_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                brave_path = p
                break

    if not brave_path:
        import shutil as _shutil_clean
        _shutil_clean.rmtree(tmp_root, ignore_errors=True)
        raise FileNotFoundError(
            "Could not find a Brave browser binary. "
            "Install brave-browser or brave-browser-beta and ensure it is on PATH."
        )

    brave_version = None
    try:
        import subprocess as _sp
        result = _sp.run(
            [brave_path, "--version"],
            capture_output=True, text=True, timeout=5
        )
        m = re.search(r"(\d+)\.\d+", result.stdout)
        if m:
            brave_version = int(m.group(1))
            log.info(f"  🔍  Detected Brave version: {brave_version}")
    except Exception as e:
        log.debug(f"  Could not detect Brave version: {e} — letting uc auto-detect")

    try:
        driver = uc.Chrome(
            options=opts,
            use_subprocess=True,
            browser_executable_path=brave_path,
            **({"version_main": brave_version} if brave_version else {}),
        )
    except Exception as exc:
        log.error(f"  ❌  Failed to launch Brave: {exc}")
        import shutil as _shutil_clean
        import time as _time_wait
        _time_wait.sleep(1)
        _shutil_clean.rmtree(tmp_root, ignore_errors=True)
        raise

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    driver._auto_tmp_profile = tmp_root  # type: ignore[attr-defined]
    log.info(
        "  🚀  Brave window launched (isolated temp profile, "
        "your real browser is unaffected)"
    )
    return driver


def verify_linkedin_freshness_via_snippet(title: str, snippet: str, company_name: str, log: logging.Logger) -> bool:
    """
    Checks Brave Search result title and snippet to see if the contact has already left the company.
    Requires no profile page visit or API quota, completely bypassing anti-scraping controls.
    """
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    norm_company = company_name.lower().replace("inc", "").replace("ltd", "").replace("pvt", "").strip(" .-,")

    # Ex-employee indicators
    ex_words = ["ex-", " ex ", "past", "former", "formerly", "previous"]

    # Check if any ex-word is present along with the company name in title or snippet
    for word in ex_words:
        if word in title_lower or word in snippet_lower:
            # If the snippet indicates they left the target company
            if norm_company in title_lower or norm_company in snippet_lower:
                log.info(f"      ✕ Snippet pre-check: Discarded stale contact (found ex-word '{word}' near '{company_name}').")
                return False

    # Check for past date ranges in the snippet (e.g. 2021 - 2023 or similar)
    if re.search(r"\b20\d{2}\s*-\s*(?:20)?\d{2}\b", snippet_lower):
        if norm_company in snippet_lower and "present" not in snippet_lower:
            log.info(f"      ✕ Snippet pre-check: Discarded stale contact (found past date range near '{company_name}').")
            return False

    return True

# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 2 — Y COMBINATOR  (DO NOT TOUCH — unchanged from v3)
#  WHY SELENIUM: YC's Algolia endpoint returns 403 "Host not in allowlist" for
#  ALL server-side requests. Only the browser's own JS context is allowed.
# ══════════════════════════════════════════════════════════════════════════════

class YCSource:
    """
    Scrapes the Y Combinator company directory using a real browser.
    hiring_signal = "yc_batch".
    """

    _log = logging.getLogger("pipeline.YCSource")

    _ALGOLIA_APP_ID = "45BWZJ1SGC"
    _ALGOLIA_INDEX  = "YCCompany_production"
    _ALGOLIA_KEY    = "NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlhYTZjOTJiMjlhMWFuYWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlfQnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE"

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 2/4 : Y Combinator (India Hiring)  ━━━━")
        
        # We perform a single request for all hiring South Asia companies
        companies = self._fetch_api()
        
        seen: set[str] = set()
        unique: list[Company] = []
        for c in companies:
            key = normalize_company_name(c["name"])
            if key and key not in seen:
                seen.add(key)
                unique.append(c)

        self._log.info(f"✅  YC complete — {len(unique)} unique hiring companies found")
        return unique

    def _fetch_api(self) -> list[Company]:
        """Fetch all South Asia hiring companies using the Algolia API."""
        url = f"https://{self._ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
        
        headers = {
            "Content-Type": "application/json",
            "x-algolia-application-id": self._ALGOLIA_APP_ID,
            "x-algolia-api-key": self._ALGOLIA_KEY,
            "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser; JS Helper (3.16.1)",
            "Referer": "https://www.ycombinator.com/",
        }

        # New strategy: Ignore batches, target Region: South Asia + Hiring: True
        params = (
            "query=&hitsPerPage=1000"
            "&maxValuesPerFacet=1000"
            "&page=0"
            "&facetFilters=%5B%5B%22isHiring%3Atrue%22%5D%2C%5B%22regions%3ASouth%20Asia%22%5D%5D"
            "&facets=%5B%22app_answers%22%2C%22app_video_public%22%2C%22batch%22%2C%22demo_day_video_public%22%2C%22industries%22%2C%22isHiring%22%2C%22nonprofit%22%2C%22question_answers%22%2C%22regions%22%2C%22subindustry%22%2C%22top_company%22%5D"
        )

        payload = {
            "requests": [
                {
                    "indexName": self._ALGOLIA_INDEX,
                    "params": params
                }
            ]
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            hits = data.get("results", [{}])[0].get("hits", [])
            companies = []
            for hit in hits:
                name = hit.get("name", "")
                slug = hit.get("slug", "")
                if not name or not slug:
                    continue
                
                # Geolocation verification: ensure actual Indian presence (Bengaluru, Pune, India, etc.)
                # Filter out US-headquartered global startups indexed under YC "South Asia" due to founder origin.
                location_str = ""
                for loc_field in ["location", "all_locations", "headquarters"]:
                    val = hit.get(loc_field)
                    if val and isinstance(val, str):
                        location_str += " " + val
                
                loc_list = hit.get("locations")
                if loc_list and isinstance(loc_list, list):
                    location_str += " " + " ".join(str(l) for l in loc_list)
                    
                location_str = location_str.lower()
                
                indian_cities = [c.lower() for c in TARGET_COMPANY_CRITERIA["locations"]] + ["india"]
                has_indian_presence = any(city in location_str for city in indian_cities)
                
                if not has_indian_presence:
                    self._log.debug(f"  ✕ YC: Skipped '{name}' (outside target Indian locations, found: '{location_str.strip()}')")
                    continue
                
                # Employee size check (Implements TARGET_COMPANY_CRITERIA["employee_range"])
                team_size = hit.get("team_size") or hit.get("employee_count") or hit.get("size")
                if team_size and isinstance(team_size, (int, float)):
                    min_emp, max_emp = TARGET_COMPANY_CRITERIA["employee_range"]
                    if not (min_emp <= team_size <= max_emp):
                        self._log.debug(f"  ✕ YC: Skipped '{name}' (employee count {team_size} outside target sweet spot {min_emp}-{max_emp})")
                        continue
                
                companies.append(Company(
                    name=name,
                    source="yc",
                    source_url=f"https://www.ycombinator.com/companies/{slug}",
                    discovered_at=_today_str(),
                    hiring_signal="yc_batch",
                    job_title=hit.get("one_liner", ""),
                    urgency="YC India (Active)",
                    company_description=hit.get("one_liner", ""),
                ))
            return companies
        except Exception as exc:
            self._log.error(f"  YC India API failed: {exc}")
            return []


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 3 — YOURSTORY  (P6: replaces ProductHuntSource)
#
#  WHY YOURSTORY:
#  ProductHunt was US consumer apps — almost zero India AI hiring signal.
#  YourStory.com is India's leading startup media + company directory.
#  It lists Indian startups by sector, stage, and city — far more relevant.
#
#  hiring_signal = "launch", source = "yourstory"
#  Same interface as ProductHuntSource — drop-in replacement.
# ══════════════════════════════════════════════════════════════════════════════

class YourStorySource:
    """
    Parses YourStory RSS feed to find Indian startups actively building.
    Requires no JavaScript rendering, bypassing SPA/NextJS restrictions.

    hiring_signal = "launch"  (team is actively building and visible on YourStory)
    source        = "yourstory"
    """

    _log = logging.getLogger("pipeline.YourStorySource")
    _RSS_FEED_URL = "https://yourstory.com/feed"

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 3/4 : YourStory RSS  ━━━━")
        session = _requests_session()
        companies: list[Company] = []

        try:
            resp = session.get(self._RSS_FEED_URL, timeout=15)
            resp.raise_for_status()
            companies = self._parse_rss_feed(resp.text)
            self._log.info(f"  YourStory RSS: found {len(companies)} companies")
        except requests.RequestException as exc:
            self._log.warning(f"  YS RSS fetch error: {exc}")

        # Always add curated list — reliable baseline even if scraper is blocked
        companies.extend(self._get_curated_companies())

        seen: set[str] = set()
        unique: list[Company] = []
        for c in companies:
            key = normalize_company_name(c["name"])
            if key and key not in seen:
                seen.add(key)
                unique.append(c)

        self._log.info(f"✅  YourStory RSS complete — {len(unique)} unique companies")
        return unique

    def _parse_rss_feed(self, html: str) -> list[Company]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.find_all("item")
        companies: list[Company] = []
        seen_names: set[str] = set()

        for item in items:
            title_node = item.find("title")
            link_node  = item.find("link")
            desc_node  = item.find("description")

            title = title_node.get_text(strip=True) if title_node else ""
            link  = link_node.get_text(strip=True) if link_node else ""
            desc  = desc_node.get_text(strip=True) if desc_node else ""

            # Try to extract the company name using slug or headline
            name = _extract_company_from_slug_or_headline(title, link)

            if name and len(name) > 2 and name.lower() not in seen_names:
                # Target criteria matching:
                # Check tech keywords
                tech_text = (name + " " + title + " " + desc).lower()
                has_tech = any(tech.lower() in tech_text for tech in TARGET_COMPANY_CRITERIA["must_have_tech"])
                if not has_tech:
                    self._log.debug(f"  ✕  YourStory RSS: skipped '{name}' (no matching tech keywords)")
                    continue

                # Check location if mentioned
                amount_m, stage, location = parse_funding_info(title, desc)
                if location is not None:
                    if location not in TARGET_COMPANY_CRITERIA["locations"]:
                        self._log.debug(f"  ✕  YourStory RSS: skipped '{name}' (outside target locations: {location})")
                        continue

                seen_names.add(name.lower())
                companies.append(Company(
                    name=name,
                    source="yourstory",
                    source_url=link or "https://yourstory.com",
                    discovered_at=_today_str(),
                    hiring_signal="launch",
                    job_title=f"{location or 'India'} | YourStory Launch",
                    urgency="Recent Launch",
                    company_description=desc.strip(),
                ))

        return companies

    def _get_curated_companies(self) -> list[Company]:
        """
        Curated list of India-based AI/ML startups actively building.
        Update weekly with new entrants from YourStory / Inc42 coverage.
        Only keeps Seed to Series B to bypass corporate hiring bureaucracy.
        """
        curated: list[tuple[str, str, str]] = [
            ("Sarvam AI",          "https://www.sarvam.ai",          "Seed"),
            ("Krutrim",            "https://krutrim.ai",            "Series A"),
            ("Ola Krutrim",        "https://krutrim.ai",            "Series A"),
            ("Mad Street Den",     "https://www.madstreetden.com",     "Series B"),
            ("Arya.ai",            "https://arya.ai",                "Series A"),
            ("Senseforth",         "https://senseforth.com",         "Series B"),
            ("Sigmoid",            "https://www.sigmoid.com",        "Series B"),
            ("CognitiveLab",       "https://www.cognitivelab.in",     "Seed"),
            ("InVideo",            "https://invideo.io",             "Series B"),
            ("Qure.ai",            "https://qure.ai",                "Series B"),
            ("Yellow.ai",          "https://yellow.ai",              "Series B"),
            ("Vernacular.ai",      "https://vernacular.ai",          "Series A"),
        ]

        PREFERRED_STAGES = {"Seed", "Series A", "Series B"}

        filtered_curated = [
            (name, url) for name, url, stage in curated if stage in PREFERRED_STAGES
        ]

        return [
            Company(
                name=name,
                source="yourstory",
                source_url=url,
                discovered_at=_today_str(),
                hiring_signal="launch",
                job_title="",
                urgency="Recent Launch",
            )
            for name, url in filtered_curated
        ]


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 4 — FUNDING SIGNALS  (P7: YourStory + Inc42 replace TechCrunch)
#
#  WHY THE CHANGE:
#  TechCrunch is US-centric. Indian funding rounds ($500K–$10M seed) are
#  covered by YourStory and Inc42, not TechCrunch.
#  Same regex pattern extraction, just applied to Indian media.
# ══════════════════════════════════════════════════════════════════════════════

class FundingSource:
    """
    Finds recently funded Indian AI/ML startups from YourStory and Inc42.
    Parses live XML RSS feeds directly to avoid SPA Javascript restrictions.

    hiring_signal = "funding" — tells the Enricher to find founders first.
    """

    _log = logging.getLogger("pipeline.FundingSource")

    _YS_FEED    = "https://yourstory.com/feed"
    _INC42_FEED = "https://inc42.com/tag/funding/feed/"

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 4/4 : Funding Signals (YourStory + Inc42 RSS)  ━━━━")
        session = _requests_session()
        companies: list[Company] = []

        for feed_url, label in [
            (self._YS_FEED,    "YourStory Funding RSS"),
            (self._INC42_FEED, "Inc42 Funding RSS"),
        ]:
            try:
                resp = session.get(feed_url, timeout=15)
                resp.raise_for_status()
                page_companies = self._parse_rss_feed(resp.text, label)
                self._log.info(f"  {label}: found {len(page_companies)} companies from RSS feed")
                companies.extend(page_companies)
            except requests.RequestException as exc:
                self._log.warning(f"  {label} fetch error: {exc}")

        # Curated Indian AI/ML companies with confirmed recent funding
        companies.extend(self._get_curated_funded_companies())

        seen: set[str] = set()
        unique: list[Company] = []
        for c in companies:
            key = normalize_company_name(c["name"])
            if key and key not in seen:
                seen.add(key)
                unique.append(c)

        self._log.info(f"✅  Funding RSS signals complete — {len(unique)} unique companies")
        return unique

    def _parse_rss_feed(self, html: str, source_label: str) -> list[Company]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.find_all("item")
        companies: list[Company] = []
        seen_names: set[str] = set()

        for item in items:
            title_node = item.find("title")
            link_node  = item.find("link")
            desc_node  = item.find("description")

            title = title_node.get_text(strip=True) if title_node else ""
            link  = link_node.get_text(strip=True) if link_node else ""
            desc  = desc_node.get_text(strip=True) if desc_node else ""

            # Try to extract the company name using slug or headline
            name = _extract_company_from_slug_or_headline(title, link)

            if name and len(name) > 2 and name.lower() not in seen_names:
                # Clean name + description check
                tech_text = (name + " " + title + " " + desc).lower()
                has_tech = any(tech.lower() in tech_text for tech in TARGET_COMPANY_CRITERIA["must_have_tech"])
                if not has_tech:
                    self._log.debug(f"  ✕  {source_label}: skipped '{name}' (does not match target tech keywords)")
                    continue

                amount_m, stage, location = parse_funding_info(title, desc)

                # Check 1: Stage filter
                if stage is not None:
                    if stage not in TARGET_COMPANY_CRITERIA["stages"]:
                        self._log.debug(f"  ✕  {source_label}: skipped '{name}' (unsupported stage: {stage})")
                        continue

                # Check 2: Funding Amount Filter ($500K to $5M, skip if > $10M)
                if amount_m is not None:
                    min_f, max_f = TARGET_COMPANY_CRITERIA["funding_range_usd_m"]
                    if amount_m > 10.0:
                        self._log.info(f"  ✕  {source_label}: skipped '{name}' (round too large: ${amount_m:.1f}M > $10M)")
                        continue
                    if amount_m < min_f:
                        self._log.debug(f"  ✕  {source_label}: skipped '{name}' (round too small: ${amount_m:.2f}M < ${min_f}M)")
                        continue

                # Check 3: Location Filter
                if location is not None:
                    if location not in TARGET_COMPANY_CRITERIA["locations"]:
                        self._log.debug(f"  ✕  {source_label}: skipped '{name}' (outside target locations: {location})")
                        continue

                seen_names.add(name.lower())
                companies.append(Company(
                    name=name,
                    source="funding",
                    source_url=link or "https://inc42.com",
                    discovered_at=_today_str(),
                    hiring_signal="funding",
                    job_title=f"{stage or 'Funded'} | {location or 'India'} | {f'${amount_m:.1f}M' if amount_m else 'Amount Undisclosed'}",
                    urgency="Recently Funded",
                    company_description=desc.strip(),
                ))

        return companies

    def _get_curated_funded_companies(self) -> list[Company]:
        """
        Curated list of India-focused AI/ML companies with known recent funding.
        Only keeps Seed to Series B to bypass corporate hiring bureaucracy.
        """
        curated: list[tuple[str, str, str]] = [
            ("Artivatic Data Labs", "https://artivatic.ai",           "Seed"),
            ("DevRev",             "https://devrev.ai",              "Seed"),
            ("KissanAI",           "https://kissan.ai",              "Seed"),
            ("Dubverse",           "https://dubverse.ai",            "Seed"),
            ("Murf AI",            "https://murf.ai",                "Series A"),
            ("Zippee",             "https://zippee.in",              "Seed"),
            ("Entri.app",          "https://entri.app",              "Series A"),
            ("Oben Electric",      "https://obenelectric.com",       "Series A"),
            ("Swipe",              "https://getswipe.in",            "Seed"),
        ]

        PREFERRED_STAGES = {"Seed", "Series A", "Series B"}

        filtered_curated = [
            (name, url) for name, url, stage in curated if stage in PREFERRED_STAGES
        ]

        return [
            Company(
                name=name,
                source="funding",
                source_url=url,
                discovered_at=_today_str(),
                hiring_signal="funding",
                job_title="",
                urgency="Recently Funded",
            )
            for name, url in filtered_curated
        ]


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 5 — INSTAHYRE  (Upgrade #3)
#
#  Discovers company names from Instahyre's public job listing pages.
#  Does NOT log in. Does NOT apply. 100% public HTML scraping.
#  hiring_signal = "job_post", source = "instahyre"
# ══════════════════════════════════════════════════════════════════════════════

class InstahyreSource:
    """
    Scrapes Instahyre's public job listings page for AI/ML roles.
    Extracts company names from job cards using BeautifulSoup.
    No login required — entirely public HTML.

    hiring_signal = "job_post"   source = "instahyre"
    """

    _log     = logging.getLogger("pipeline.InstahyreSource")
    _BASE    = "https://www.instahyre.com"
    _JOBS_URL = "https://www.instahyre.com/jobs/"

    # AI/ML keyword filter applied to job title text
    _ML_KEYWORDS = [
        "machine learning", "ml engineer", "ai engineer", "data scientist",
        "mlops", "data engineer", "nlp", "llm", "deep learning",
        "applied scientist", "research engineer", "computer vision",
    ]

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 5/7 : Instahyre (HTML scrape, no login)  ━━━━")
        session   = _requests_session()
        companies = self._scrape_listings(session, self._JOBS_URL, source="instahyre")
        self._log.info(f"✅  Instahyre: {len(companies)} companies discovered")
        return companies

    def _scrape_listings(
        self, session: requests.Session, url: str, source: str
    ) -> list[Company]:
        """
        Shared scraper used by NaukriSource too.
        Fetches the URL, finds job cards, extracts company + role info.
        """
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._log.warning(f"  {source} fetch error: {exc}")
            return []

        soup      = BeautifulSoup(resp.text, "html.parser")
        companies: list[Company] = []
        seen:      set[str]      = set()

        # Generic card selectors that work across Instahyre and similar sites
        job_cards = (
            soup.select("div.job-card, div.job_card, article.job, div[class*='job']")
            or soup.select("li[class*='job'], div[class*='listing'], div[class*='result']")
        )

        # Fallback: scan all visible text for company + role pairs
        if not job_cards:
            job_cards = soup.select("div, article, section")[:200]

        for card in job_cards:
            text = card.get_text(" ", strip=True).lower()
            if not any(kw in text for kw in self._ML_KEYWORDS):
                continue

            # Try to extract company name
            company_el = (
                card.select_one("[class*='company'], [class*='employer'], [class*='org']")
            )
            name = company_el.get_text(strip=True) if company_el else ""
            if not name:
                # Fallback: grab first capitalised token that looks like a name
                name = _extract_company_from_slug_or_headline(card.get_text(), url)

            if not name or not _is_valid_company_name(name):
                continue

            key = normalize_company_name(name)
            if not key or key in seen:
                continue
            seen.add(key)

            # Try to get a role title
            role_el  = card.select_one("[class*='title'], [class*='role'], h2, h3")
            job_title = role_el.get_text(strip=True) if role_el else "Active Job Post"

            # Get apply link
            link_el  = card.select_one("a[href]")
            link     = ""
            if link_el:
                href = link_el.get("href", "")
                link = href if href.startswith("http") else self._BASE + href

            companies.append(Company(
                name              = name,
                source            = source,
                source_url        = link or url,
                discovered_at     = _today_str(),
                hiring_signal     = "job_post",
                job_title         = job_title,
                urgency           = "3 - Standard (Actively Hiring)",
                company_description = "",
            ))

        return companies


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 6 — NAUKRI  (Upgrade #3)
#
#  Scrapes Naukri's public search results for AI/ML jobs in India.
#  Does NOT log in. Reuses InstahyreSource._scrape_listings().
#  hiring_signal = "job_post", source = "naukri"
# ══════════════════════════════════════════════════════════════════════════════

class NaukriSource:
    """
    Scrapes Naukri's public job search results for AI/ML roles.
    Zero login, zero cookie sessions — just public GET requests.

    Reuses InstahyreSource._scrape_listings() so both scrapers share
    the same parsing logic and stay in sync with any updates.

    hiring_signal = "job_post"   source = "naukri"
    """

    _log      = logging.getLogger("pipeline.NaukriSource")
    _SEARCH_URL = (
        "https://www.naukri.com/machine-learning-jobs"
        "?k=machine+learning+ai+engineer&l=India&experience=0"
    )

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 6/7 : Naukri (HTML scrape, no login)  ━━━━")
        session   = _requests_session()
        # Reuse InstahyreSource scraper — same structure, same keywords
        companies = InstahyreSource()._scrape_listings(
            session, self._SEARCH_URL, source="naukri"
        )
        self._log.info(f"✅  Naukri: {len(companies)} companies discovered")
        return companies


# ══════════════════════════════════════════════════════════════════════════════
#  SOURCE 7 — JOBCODE18  (Upgrade #5)
#
#  Scrapes JobCode18's public AI/ML listings — these are DIRECT
#  Greenhouse/Lever/Workable links (highest conversion, no middleman).
#  hiring_signal = "job_post", source = "jobcode18"
# ══════════════════════════════════════════════════════════════════════════════

class JobCode18Source:
    """
    Scrapes JobCode18 for AI/ML job listings with direct ATS apply links.
    These are Greenhouse/Lever/Workable redirect links — highest conversion.
    Filters for AI/ML roles before returning Company objects.

    hiring_signal = "job_post"   source = "jobcode18"
    """

    _log      = logging.getLogger("pipeline.JobCode18Source")
    _SITE_URL = "https://jobcode18.com"

    _ML_KEYWORDS = [
        "machine learning", "ml", "ai", "data scientist", "mlops",
        "data engineer", "nlp", "llm", "deep learning", "computer vision",
    ]

    def fetch_companies(self) -> list[Company]:
        self._log.info("━━━━  SOURCE 7/7 : JobCode18 (HTML scrape, direct ATS links)  ━━━━")
        session   = _requests_session()
        companies: list[Company] = []
        seen:      set[str]      = set()

        try:
            resp = session.get(self._SITE_URL, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # JobCode18 lists jobs as links with company name in title
            job_links = soup.select("a[href]")
            for a in job_links:
                text = a.get_text(" ", strip=True).lower()
                href = a.get("href", "")

                if not any(kw in text for kw in self._ML_KEYWORDS):
                    continue

                # Extract company name from link text or page context
                name = _extract_company_from_slug_or_headline(
                    a.get_text(strip=True), href
                )
                if not name or not _is_valid_company_name(name):
                    continue

                key = normalize_company_name(name)
                if not key or key in seen:
                    continue
                seen.add(key)

                full_url = href if href.startswith("http") else self._SITE_URL + href

                companies.append(Company(
                    name              = name,
                    source            = "jobcode18",
                    source_url        = full_url,
                    discovered_at     = _today_str(),
                    hiring_signal     = "job_post",
                    job_title         = a.get_text(strip=True),
                    urgency           = "2 - Recent (within 7 days)",  # JC18 lists are fresh
                    company_description = "",
                ))

        except requests.RequestException as exc:
            self._log.warning(f"  JobCode18 fetch error: {exc}")

        self._log.info(f"✅  JobCode18: {len(companies)} companies found")
        return companies


# ══════════════════════════════════════════════════════════════════════════════
#  CAREER PORTAL FINDER  (Upgrade #4)
#
#  Runs INSIDE Enricher._enrich_company() after contact enrichment.
#  For each company, fires 4 Brave queries and drops the best matching URL
#  into the corresponding sheet column.
#
#  Result: the Google Sheet becomes a one-click launchpad.
#    Careers URL  → Greenhouse/Lever/Workable/Ashby (direct apply)
#    Wellfound URL → wellfound.com/company/<slug> (1-click Wellfound apply)
#    Naukri URL   → naukri.com search result (reference only)
#    Instahyre URL → instahyre.com search result (reference only)
# ══════════════════════════════════════════════════════════════════════════════

class CareerPortalFinder:
    """
    Finds ALL apply links for a company and returns them as a dict.
    Called per-company during enrichment — results are written to new sheet columns.

    Usage:
        finder = CareerPortalFinder()
        links  = finder.find_all_links("Sarvam AI")
        # → {"careers_url": "https://boards.greenhouse.io/sarvamai/…",
        #    "wellfound_url": "https://wellfound.com/company/sarvam-ai",
        #    "naukri_url":    "…",
        #    "instahyre_url": "…"}
    """

    _log = logging.getLogger("pipeline.CareerPortalFinder")

    # Brave queries keyed by the column they populate
    _SEARCH_TEMPLATES: dict[str, str] = {
        "careers_url": (
            '"{company}" careers apply '
            'site:greenhouse.io OR site:lever.co OR site:workable.com OR site:jobs.ashbyhq.com'
        ),
        "wellfound_url": 'site:wellfound.com "{company}"',
        "naukri_url":    'site:naukri.com "{company}" AI OR ML OR "machine learning"',
        "instahyre_url": 'site:instahyre.com "{company}"',
    }

    def find_all_links(self, company: str) -> dict[str, str]:
        """
        Returns a dict mapping column names → URLs.
        Empty string for any link that could not be found.
        Never raises — failures are silently logged.
        """
        if not CFG.BRAVE_API_KEY:
            self._log.debug("  CareerPortalFinder: BRAVE_API_KEY not set — skipping")
            return {}

        links: dict[str, str] = {}
        headers = {
            "Accept":               "application/json",
            "X-Subscription-Token": CFG.BRAVE_API_KEY,
        }

        for col, template in self._SEARCH_TEMPLATES.items():
            query = template.format(company=company)
            try:
                resp = requests.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers=headers,
                    params={"q": query, "count": 3, "safesearch": "off"},
                    timeout=8,
                )
                if resp.status_code == 200:
                    results = resp.json().get("web", {}).get("results", [])
                    if results:
                        url = results[0].get("url", "")
                        if url:
                            links[col] = url
                            self._log.debug(f"  CareerPortalFinder [{col}]: {url}")
                elif resp.status_code == 429:
                    self._log.warning("  CareerPortalFinder: Brave quota hit — stopping")
                    break
            except Exception as exc:
                self._log.debug(f"  CareerPortalFinder [{col}] error: {exc}")

            time.sleep(0.5)   # polite pacing — 4 calls/company

        return links


# ══════════════════════════════════════════════════════════════════════════════
#  SEEN COMPANIES CACHE  (P4)
#
#  Prevents the same company from being enriched on consecutive weekly runs.
#  Stored in the existing pipeline_cache.db — new table, no new file.
#  TTL: 30 days — companies re-enter the pipeline monthly so fresh cohorts
#  don't get permanently blocked after the first enrichment pass.
# ══════════════════════════════════════════════════════════════════════════════

class SeenCompaniesCache:
    """
    Cross-run deduplication using the existing SQLite cache DB.

    Table: seen_companies
    Schema: name_key TEXT PRIMARY KEY, name_orig TEXT, seen_at REAL

    filter_new()  — call before enrichment; returns only unseen companies
    mark_seen()   — call after enrichment; records which companies were processed
    """

    _log = logging.getLogger("pipeline.SeenCompaniesCache")
    # TTL = 30 days — companies re-enter the pipeline each month

    def __init__(self, db_path: str = CFG.CACHE_DB_PATH) -> None:
        self._db_path = db_path
        self._init_table()

    def _init_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_companies (
                    name_key   TEXT PRIMARY KEY,
                    name_orig  TEXT NOT NULL,
                    seen_at    REAL NOT NULL
                )
            """)

    def filter_new(self, companies: list[Company]) -> list[Company]:
        """Return only companies not seen in the last 30 days to keep the pipeline fresh each month."""
        new_list    = []
        skipped     = 0
        cutoff      = time.time() - (30 * 24 * 3600)   # 30 days ago (1 month)

        with sqlite3.connect(self._db_path) as conn:
            for c in companies:
                key = normalize_company_name(c["name"])
                if not key:
                    continue
                # Check if company exists in DB and was enriched within the 30-day window
                row = conn.execute(
                    "SELECT 1 FROM seen_companies WHERE name_key = ? AND seen_at > ?", (key, cutoff)
                ).fetchone()
                if row:
                    skipped += 1
                else:
                    new_list.append(c)

        self._log.info(
            f"  SeenCompaniesCache: {len(new_list)} new companies, "
            f"skipped {skipped} previously seen companies"
        )
        return new_list

    def mark_seen(self, companies: list[Company]) -> None:
        """Record companies as seen so they are skipped on the next run."""
        now = time.time()
        with sqlite3.connect(self._db_path) as conn:
            for c in companies:
                key = normalize_company_name(c["name"])
                if key:
                    conn.execute(
                        "INSERT OR REPLACE INTO seen_companies "
                        "(name_key, name_orig, seen_at) VALUES (?, ?, ?)",
                        (key, c["name"], now),
                    )
        self._log.info(f"  SeenCompaniesCache: marked {len(companies)} companies as seen")


# ══════════════════════════════════════════════════════════════════════════════
#  IITK ALUMNI STANDALONE MODULE  (P8)
#
#  Runs AFTER company enrichment, independently.
#  Does NOT tie queries to any specific company — searches all of LinkedIn.
#  Output → "IITK Alumni" tab in the same Google Sheet.
#  Brave quota: 8 queries x 4 weeks = 32 queries/month (within agreed budget).
#  Deduplication: seen_alumni table in SQLite, TTL = 30 days.
#
#  Contact acceptance rates for fresh IITK grad:
#    IITK alumni    60–70%   ← this module surfaces these
#    Founder        30–40%
#    Tech lead      20–30%
#    Recruiter      10–15%
# ══════════════════════════════════════════════════════════════════════════════

# ── Dynamic Inverted IITK Alumni Queries (Fix 3 & V2 Queries) ─────────────────
# We run 3 general high-precision queries from the user, and batch up to 5
# cross-referencing queries for discovered small startups to guarantee relevance.
IITK_ALUMNI_QUERIES_V2: list[str] = [
    '"IIT Kanpur" (Founder OR CTO OR CEO) ("Series A" OR "Seed") India "linkedin.com/in"',
    '"IIT Kanpur" "Y Combinator" (Founder OR CEO OR CTO) India "linkedin.com/in"',
    '"IIT Kanpur" ("Founder" OR "Co-founder" OR "founding engineer" OR "early engineer") ("2021" OR "2022" OR "2023" OR "2024") "linkedin.com/in"',
]

_ALUMNI_EXCLUSIONS = (
    ' -Google -Microsoft -Amazon -Meta -Facebook -Apple -Netflix -Flipkart -Paytm -PhonePe '
    '-Ola -Swiggy -Zomato -Cred -Meesho -Zepto -Blinkit -TCS -Infosys -Wipro -Cognizant '
    '-Accenture -HCL -Capgemini -Salesforce -Oracle -Adobe -IBM -Cisco -dhruva -zoho -freshworks'
)


class IITKAlumniSource:
    """
    Inverted IITK Alumni Module: 
    Finds early-stage startups and cross-references them to identify IITK alumni.
    """

    _log = logging.getLogger("pipeline.IITKAlumniSource")

    ALUMNI_TAB     = "IITK Alumni"
    ALUMNI_HEADERS = ["Name", "Title", "Company", "LinkedIn URL", "Score", "Date Found"]
    ALUMNI_TTL_DAYS = 30

    def __init__(self) -> None:
        self._cache = QueryCache()
        self._init_seen_alumni_table()

    def _init_seen_alumni_table(self) -> None:
        with sqlite3.connect(CFG.CACHE_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_alumni (
                    linkedin_url TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    seen_at      REAL NOT NULL
                )
            """)

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self, companies: list[Company] = None) -> list[dict]:
        """Execute cross-referencing & general alumni queries and return deduplicated, scored results."""
        self._log.info("━━━━  PHASE 3 : IITK Alumni Module (Inverted)  ━━━━")
        
        # 1. Gather all unique early-stage target company names
        target_companies = set()
        if companies:
            for c in companies:
                if c.get("name"):
                    target_companies.add(c["name"])

        # Pull previously enriched early-stage startups from database
        try:
            with sqlite3.connect(CFG.CACHE_DB_PATH) as conn:
                rows = conn.execute("SELECT name_orig FROM seen_companies").fetchall()
                for r in rows:
                    if r[0]:
                        target_companies.add(r[0])
        except Exception as e:
            self._log.debug(f"Could not load seen companies: {e}")

        # Fallback to standard high-quality baseline startups to guarantee results
        if len(target_companies) < 5:
            baseline = [
                "Sarvam AI", "Krutrim", "Ola Krutrim", "Mad Street Den", "Arya.ai", 
                "Senseforth", "Sigmoid", "Artivatic Data Labs", "Anscer Robotics", 
                "Oben Electric", "Swipe", "Zippee", "Entri.app"
            ]
            for b in baseline:
                target_companies.add(b)

        # 2. Build cross-referencing queries
        company_list = list(target_companies)
        batch_size = 5
        cross_ref_queries = []
        for i in range(0, len(company_list), batch_size):
            batch = company_list[i : i + batch_size]
            company_clauses = " OR ".join(f'"{c}"' for c in batch)
            query = f'("IIT Kanpur" OR "IITK") ({company_clauses}) "linkedin.com/in"'
            cross_ref_queries.append(query)

        # 3. Assemble full query set: 3 general v2 queries + up to 5 cross-ref queries (exactly 8 queries budget)
        active_queries = []
        for q in IITK_ALUMNI_QUERIES_V2:
            active_queries.append(q)
        
        for q in cross_ref_queries[:5]:
            active_queries.append(q)

        self._log.info(f"  IITK Alumni: constructed {len(active_queries)} inverted & general queries (budget: 8)")

        raw_alumni: list[dict] = []
        seen_urls:  set[str]   = set()

        LARGE_COMPANIES_BLACKLIST = {
            "google", "microsoft", "amazon", "meta", "facebook", "apple", "netflix", "flipkart", "paytm", "phonepe",
            "ola", "swiggy", "zomato", "cred", "meesho", "zepto", "blinkit", "tcs", "infosys", "wipro", "cognizant",
            "accenture", "hcl", "capgemini", "salesforce", "oracle", "adobe", "ibm", "cisco", "dhruva", "zoho", "freshworks"
        }

        for i, query in enumerate(active_queries, start=1):
            self._log.info(f"  Alumni query {i}/{len(active_queries)}: {query[:72]}…")

            # Check cache first
            cached = self._cache.get(query)
            if cached is not None:
                items = cached
                self._log.debug(f"    Cache hit — {len(items)} results")
            else:
                items, quota_hit = self._execute_query(query)
                if items:
                    self._cache.set(query, items)
                if quota_hit:
                    self._log.warning("  ⚠  Brave quota hit — stopping alumni queries early")
                    break
                if items is None:
                    items = []

            for item in items:
                url = _strip_tracking(item.get("link", ""))
                if not url or "linkedin.com/in/" not in url.lower():
                    continue
                if url in seen_urls:
                    continue
                if self._is_seen_recently(url):
                    continue

                snippet = item.get("snippet", "") or ""

                # Code-level corporate/large company exclusion (Fixes Flaw 5 query length limit check)
                text_lower = (item.get("title", "") + " " + snippet).lower()
                is_blacklisted = False
                for blacklisted_co in LARGE_COMPANIES_BLACKLIST:
                    if re.search(r'\b' + re.escape(blacklisted_co) + r'\b', text_lower):
                        is_blacklisted = True
                        break
                if is_blacklisted:
                    self._log.debug(f"    ✕ Skipping big-tech/corporate alumnus '{url}' (matched blacklist keyword).")
                    continue

                # Hard exclusion check on snippet for employee counts (Fix 3)
                exclude_employee_snippets = [
                    "1,001-5,000", "5,001-10,000", "10,001+", 
                    "501-1,000", "201-500", "10001+", "5000+", "10000+",
                    "200+ employees", "500+ employees", "1000+ employees", "5000+ employees"
                ]
                if any(x in snippet for x in exclude_employee_snippets):
                    self._log.debug(f"    ✕ Skipping large-company alumnus '{url}' based on snippet size count.")
                    continue

                # Keep 51-200 range only if there is founding team context present
                if "51-200" in snippet:
                    founding_keywords = ["founder", "co-founder", "cto", "ceo", "founding", "early", "start-up", "startup"]
                    text_lower = (item.get("title", "") + " " + snippet).lower()
                    if not any(kw in text_lower for kw in founding_keywords):
                        self._log.debug(f"    ✕ Skipping alumnus '{url}': '51-200' range found but no founding context in snippet.")
                        continue

                name, title = Scorer.parse_profile_title(item.get("title", ""))
                score = self._score_alumnus(title)

                # Try to extract the company name from title or snippet
                company_name = "Unknown"
                if " at " in title:
                    parts = title.split(" at ")
                    if len(parts) > 1:
                        company_name = parts[-1].strip()
                elif " | " in title:
                    parts = title.split(" | ")
                    for p in parts:
                        if "at " in p.lower():
                            company_name = p.lower().split("at ")[-1].strip().capitalize()
                            break

                raw_alumni.append({
                    "name":         name,
                    "title":        title,
                    "company":      company_name,
                    "linkedin_url": url,
                    "score":        score,
                    "date_found":   _today_str(),
                })

            time.sleep(CFG.API_DELAY_S)

        raw_alumni.sort(key=lambda x: x["score"], reverse=True)
        self._log.info(f"✅  IITK Alumni: {len(raw_alumni)} unique alumni found")

        return raw_alumni

    def write_to_sheet(self, alumni: list[dict]) -> None:
        """Write alumni list to the 'IITK Alumni' tab in the same Google Sheet."""
        if not alumni:
            self._log.info("  No alumni to write.")
            return

        if not os.path.exists(CFG.GOOGLE_CREDENTIALS_FILE):
            self._log.error(f"  Credentials file not found: {CFG.GOOGLE_CREDENTIALS_FILE}")
            return

        creds = GCredentials.from_service_account_file(
            CFG.GOOGLE_CREDENTIALS_FILE,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc = gspread.authorize(creds)

        try:
            sh = gc.open(CFG.GOOGLE_SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            self._log.error(
                f"  Sheet '{CFG.GOOGLE_SHEET_NAME}' not found — run main pipeline first."
            )
            return

        try:
            ws = sh.worksheet(self.ALUMNI_TAB)
            self._log.info(f"  Opened existing '{self.ALUMNI_TAB}' tab")
            
            existing_urls = set()
            try:
                col_vals = ws.col_values(4)
                for val in col_vals:
                    val_clean = str(val).strip()
                    if val_clean and val_clean.startswith("http"):
                        existing_urls.add(val_clean)
                self._log.info(f"  Loaded {len(existing_urls)} existing alumni URLs from Google Sheets to prevent duplicates.")
            except Exception as e:
                self._log.warning(f"  Could not load existing alumni URLs from worksheet: {e}")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=self.ALUMNI_TAB, rows=500, cols=10)
            ws.append_row(self.ALUMNI_HEADERS)
            ws.freeze(rows=1)
            self._log.info(f"  Created '{self.ALUMNI_TAB}' tab with headers")
            existing_urls = set()

        rows = []
        duplicates = 0
        for a in alumni:
            url = a["linkedin_url"].strip()
            if url in existing_urls:
                duplicates += 1
                continue
            rows.append([
                a["name"],
                a["title"],
                a.get("company", "Unknown"),
                url,
                a["score"],
                a["date_found"]
            ])
            existing_urls.add(url)

        if rows:
            # Batch write (avoid quota issues)
            for i in range(0, len(rows), 50):
                ws.append_rows(rows[i : i + 50], value_input_option="USER_ENTERED")
                time.sleep(0.5)
            self._log.info(f"✅  Wrote {len(rows)} new alumni to '{self.ALUMNI_TAB}' tab ({duplicates} duplicates skipped).")
        else:
            self._log.info(f"  No new alumni to write ({duplicates} duplicates skipped).")
        
        # Mark as seen only after successful write
        self._mark_seen(alumni)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _score_alumnus(self, title: str) -> int:
        t = title.lower()
        # Check highest tier first to avoid partial matches inflating score
        if any(kw in t for kw in ("founder", "co-founder", "ceo", "cto")):
            return 5
        if any(kw in t for kw in ("vp engineering", "vp of engineering", "head of engineering")):
            return 4
        if "engineering manager" in t:
            return 3
        if any(kw in t for kw in ("tech lead", "senior engineer", "senior ml", "senior ai", "senior data")):
            return 2
        return 1

    def _is_seen_recently(self, url: str) -> bool:
        cutoff = time.time() - self.ALUMNI_TTL_DAYS * 86_400
        with sqlite3.connect(CFG.CACHE_DB_PATH) as conn:
            row = conn.execute(
                "SELECT seen_at FROM seen_alumni WHERE linkedin_url = ?", (url,)
            ).fetchone()
        return bool(row and row[0] > cutoff)

    def _mark_seen(self, alumni: list[dict]) -> None:
        now = time.time()
        with sqlite3.connect(CFG.CACHE_DB_PATH) as conn:
            for a in alumni:
                conn.execute(
                    "INSERT OR REPLACE INTO seen_alumni (linkedin_url, name, seen_at) "
                    "VALUES (?, ?, ?)",
                    (a["linkedin_url"], a["name"], now),
                )

    def _execute_query(self, query: str) -> tuple[list[dict], bool]:
        """Direct Brave API call — same pattern as Enricher._execute_query_with_retry."""
        if not CFG.BRAVE_API_KEY:
            self._log.error("BRAVE_API_KEY is not set — cannot run alumni queries")
            return [], False

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": CFG.BRAVE_API_KEY,
        }
        params = {
            "q":          query,
            "count":      CFG.CSE_RESULTS_PER_QUERY,
            "safesearch": "off",
        }

        for attempt in range(CFG.MAX_RETRIES):
            try:
                resp = requests.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers=headers,
                    params=params,
                    timeout=12,
                )
                if resp.status_code == 429:
                    self._log.warning("  ⚠  Brave 429 — alumni quota hit")
                    return [], True
                resp.raise_for_status()
                data = resp.json()
                raw  = data.get("web", {}).get("results", [])
                items = [
                    {
                        "link":    r.get("url"),
                        "title":   r.get("title"),
                        "snippet": r.get("description"),
                    }
                    for r in raw
                ]
                return items, False

            except requests.exceptions.Timeout:
                sleep_for = (CFG.BACKOFF_BASE_S ** attempt) + random.uniform(0.2, 1.2)
                self._log.warning(
                    f"  ⚠  Timeout (attempt {attempt + 1}/{CFG.MAX_RETRIES}) "
                    f"— retry in {sleep_for:.1f}s…"
                )
                time.sleep(sleep_for)

            except requests.exceptions.RequestException as exc:
                self._log.error(f"  ❌  Alumni query network error: {exc}")
                break

        return [], False


# ══════════════════════════════════════════════════════════════════════════════
#  RELEVANCE PRE-FILTER  (P5)
#
#  Applied BEFORE enrichment. Skips companies with no AI/ML keywords in
#  their name or job_title — saves Brave quota on irrelevant targets.
#
#  Wellfound companies also require salary within 8–15 LPA where available.
#  If no salary is disclosed, the company is KEPT (cannot filter undisclosed).
# ══════════════════════════════════════════════════════════════════════════════

_RELEVANCE_KEYWORDS: frozenset[str] = frozenset({
    "ai", "ml", "machine learning", "data", "llm", "nlp", "analytics",
    "python", "deep learning", "computer vision", "mlops", "generative", "rag",
    "intelligence", "neural", "model", "platform", "infra", "engineer",
})

# Corporate giants and massive service companies with rigid hiring pipelines (Fix 2)
_SKIP_LARGE_COMPANIES: frozenset[str] = frozenset({
    # Indian IT Giants / Service Corporates
    "tcs", "tata consultancy services", "infosys", "wipro", "cognizant", "accenture", 
    "hcl", "hcltech", "tech mahindra", "l&t", "ltimindtree", "capgemini", "genpact", "wns",
    # Global Big Tech / Product Giants
    "google", "microsoft", "amazon", "meta", "facebook", "apple", "netflix", "salesforce", 
    "oracle", "adobe", "sap", "cisco", "ibm", "intel", "nvidia", "amd", "qualcomm", "dell",
    "hp", "lenovo", "samsung", "sony", "huawei", "tencent", "alibaba", "bytedance", "baidu",
    # Large Indian Unicorns / Tech Giants (500+ or mature stage)
    "flipkart", "paytm", "phonepe", "ola", "uber", "swiggy", "zomato", "byjus", "byju's", 
    "cred", "meesho", "nykaa", "lenskart", "unacademy", "upgrad", "eruditus", "zepto", 
    "blinkit", "groww", "zerodha", "razorpay", "pine labs", "policybazaar", "inmobi",
    "delhivery", "makemytrip", "yatra", "bookmyshow", "freshworks", "zoho", "dhruva", 
    "highradius", "gupshup", "chargebee", "iifl", "hdfc", "icici", "sbi", "axis bank",
    # Specific Corporate / Mid-Large Tech (hiring is highly bureaucratic)
    "haptik", "browserstack", "mindtickle", "fractal", "fractal analytics", "postman",
    "observe.ai", "observe", "yellow.ai", "yellow", "reliance", "jio", "airtel", "adani", 
    "tata", "birla", "vedanta", "mahindra", "godrej",
})


def _passes_relevance_filter(company: Company) -> bool:
    """
    Return True if the company has any AI/ML relevance signal and is NOT a massive corporate giant.

    For Wellfound (job_post) companies we check name + job_title.
    For other sources we enforce target tech check and filter corporate/global giants.
    """
    name_clean = normalize_company_name(company.get("name", ""))
    
    # ── P10 (Fix 2): Skip known corporate giants & bureaucratic firms
    if name_clean in _SKIP_LARGE_COMPANIES:
        logging.getLogger("pipeline.RelevanceFilter").info(f"  ✕  Skipping corporate giant (pre-filter): '{company.get('name')}'")
        return False
        
    for skip_co in _SKIP_LARGE_COMPANIES:
        if f" {skip_co} " in f" {name_clean} ":
            logging.getLogger("pipeline.RelevanceFilter").info(f"  ✕  Skipping corporate giant (pre-filter match '{skip_co}'): '{company.get('name')}'")
            return False

    # ── Skip Global / US Supplemental Companies (Mistral, Modal, Together AI, etc.)
    global_skips = {"mistral", "together", "modal", "replicate", "weaviate", "qdrant", "anthropic", "openai", "cohere", "midjourney"}
    if any(g in name_clean for g in global_skips):
        logging.getLogger("pipeline.RelevanceFilter").info(f"  ✕  Skipping global/US company (pre-filter): '{company.get('name')}'")
        return False

    text = (
        company.get("name", "") + " " + company.get("job_title", "")
    ).lower()

    # Enforce must-have tech filter
    has_tech = any(kw.lower() in text for kw in TARGET_COMPANY_CRITERIA["must_have_tech"])
    if not has_tech:
        # If it's a job post, skip immediately
        if company.get("hiring_signal") == "job_post":
            logging.getLogger("pipeline.RelevanceFilter").info(f"  ✕  Skipping on tech relevance: '{company.get('name')}'")
            return False
            
    return True



# ══════════════════════════════════════════════════════════════════════════════
#  MULTI-SOURCE COLLECTOR  (updated: producthunt → yourstory)
# ══════════════════════════════════════════════════════════════════════════════

class MultiSourceCollector:
    """
    Runs enabled sources, normalizes output, deduplicates, and returns
    a unified Company list for the Enricher.

    Source priority (preserved through deduplication):
      wellfound > yc > yourstory > funding
    """

    _log = logging.getLogger("pipeline.MultiSourceCollector")

    _ALL_SOURCES = {
        "wellfound":  WellfoundSource,
        "yc":         YCSource,
        "yourstory":  YourStorySource,
        "funding":    FundingSource,
        "instahyre":  InstahyreSource,   # Upgrade #3
        "naukri":     NaukriSource,      # Upgrade #3
        "jobcode18":  JobCode18Source,   # Upgrade #5
    }

    def __init__(self, active_sources: str = "all") -> None:
        if active_sources.strip().lower() == "all":
            self._active = list(self._ALL_SOURCES.keys())
        else:
            requested = [s.strip().lower() for s in active_sources.split(",")]
            self._active = [s for s in requested if s in self._ALL_SOURCES]
            unknown = [s for s in requested if s not in self._ALL_SOURCES]
            if unknown:
                self._log.warning(f"Unknown sources ignored: {unknown}")

        self._log.info(f"Active sources: {self._active}")

    def run(self) -> list[Company]:
        self._log.info("━━━━━━━━  PHASE 1 : Multi-Source Discovery  ━━━━━━━━")

        all_companies: list[Company] = []
        source_counts: dict[str, int] = {}

        for source_name in self._active:
            source_cls = self._ALL_SOURCES[source_name]
            try:
                companies = source_cls().fetch_companies()
                source_counts[source_name] = len(companies)
                all_companies.extend(companies)
                self._log.info(f"  ✓  {source_name}: {len(companies)} companies")
            except Exception as exc:
                source_counts[source_name] = 0
                self._log.error(
                    f"  ❌  Source '{source_name}' failed: {exc}\n"
                    + traceback.format_exc(limit=3)
                )

        before_dedup = len(all_companies)
        unique = deduplicate_companies(all_companies)
        removed = before_dedup - len(unique)

        self._log.info("  ─── Discovery Summary ───────────────────────────")
        for source_name, count in source_counts.items():
            self._log.info(f"    {source_name:<16} {count:>4} companies")
        self._log.info(f"    {'TOTAL (raw)':<16} {before_dedup:>4}")
        self._log.info(f"    {'Duplicates removed':<16} {removed:>4}")
        self._log.info(f"    {'Unique (final)':<16} {len(unique):>4}")
        self._log.info("  ─────────────────────────────────────────────────")

        return unique


# ══════════════════════════════════════════════════════════════════════════════
#  UNCHANGED FROM v2/v3: categorize_urgency, Scorer, QueryCache
#  DO NOT MODIFY THESE SECTIONS — they work correctly and are tested.
# ══════════════════════════════════════════════════════════════════════════════

def categorize_urgency(time_string: str) -> str:
    text = time_string.lower()
    if any(kw in text for kw in ("hour", "today", "yesterday", "1 day", "just")):
        return "1 - High Priority (<24h)"
    if any(kw in text for kw in ("day", "1 week", "2 day", "3 day", "4 day", "5 day", "6 day")):
        return "2 - Medium Priority (1 Week)"
    return "3 - Standard (Actively Hiring)"


class Scorer:
    """
    Stateless relevance scoring — identical logic to v2.
    All five scoring blocks preserved exactly; no regression risk.
    """

    _log = logging.getLogger("pipeline.Scorer")

    _NEGATIVE_TOKENS: tuple[str, ...] = (
        "ex-", " ex ", "past", "previous", "formerly", "former",
        "speaker", "event", "investor", "advisor", "podcast", "mentor",
    )

    @classmethod
    def parse_profile_title(cls, raw_title: str) -> tuple[str, str]:
        title = re.sub(r"(?i)\s+[-|–•:]\s+linkedin\s*$", "", raw_title).strip()
        parts = re.split(r"\s+[-–|•:]\s+", title, maxsplit=1)

        if len(parts) == 2:
            name, role = parts[0].strip(), parts[1].strip()
        elif len(parts) == 1:
            name, role = parts[0].strip(), "Unparsed — verify URL"
        else:
            name, role = "Unknown", "Unknown"

        cls._log.debug(f"  parse_profile_title: {name!r} / {role!r}")
        return name, role

    @classmethod
    def calculate_relevance_score(
        cls,
        name:            str,
        title:           str,
        snippet:         str,
        company:         str,
        target_keywords: list[str],
    ) -> int:
        score   = 0
        t_lower = title.lower()
        s_lower = snippet.lower()

        raw_tokens = re.split(r"[\s,.\-]+", company.lower())
        full_name   = company.lower().strip()

        company_tokens = [
            tok for tok in raw_tokens
            if len(tok) > 2 or (len(tok) > 0 and full_name == tok)
        ]

        if any(tok in t_lower for tok in company_tokens):
            score += 2
            cls._log.debug(f"    [+2] Company match in TITLE    (tokens={company_tokens})")

        if any(tok in s_lower for tok in company_tokens):
            score += 1
            cls._log.debug("    [+1] Company match in SNIPPET")

        if any(kw.lower() in t_lower for kw in target_keywords):
            score += 2
            cls._log.debug("    [+2] Keyword match in TITLE")

        if any(kw.lower() in s_lower for kw in target_keywords):
            score += 1
            cls._log.debug("    [+1] Keyword match in SNIPPET")

        if len(name) > CFG.MAX_NAME_LENGTH:
            score -= 1
            cls._log.debug(f"    [-1] Name too long ({len(name)} chars)")

        combined = t_lower + " " + s_lower
        if any(neg in combined for neg in cls._NEGATIVE_TOKENS):
            score -= 2
            cls._log.debug("    [-2] Negative token detected")

        # Alumni bonus — IITK in title or snippet means very high response likelihood.
        _IITK_TOKENS = ("iit kanpur", "iitk", "indian institute of technology kanpur")
        combined = (title + " " + snippet).lower()
        if any(tok in combined for tok in _IITK_TOKENS):
            score += 3
            cls._log.debug("    [+3] IITK alumni detected — priority boosted")

        cls._log.debug(f"    → Final score for {name!r}: {score}")
        return score


class QueryCache:
    """SQLite query cache — identical to v2. DO NOT MODIFY."""

    _log = logging.getLogger("pipeline.QueryCache")

    def __init__(self, db_path: str = CFG.CACHE_DB_PATH) -> None:
        self._db_path     = db_path
        self._ttl_seconds = CFG.CACHE_TTL_DAYS * 86_400
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cse_cache (
                    query_hash TEXT PRIMARY KEY,
                    query      TEXT NOT NULL,
                    results    TEXT NOT NULL,
                    cached_at  REAL NOT NULL
                )
                """
            )
        self._log.debug(f"Cache DB ready: {self._db_path}")

    def get(self, query: str) -> Optional[list[dict]]:
        h      = self._hash(query)
        cutoff = time.time() - self._ttl_seconds

        with self._connect() as conn:
            row = conn.execute(
                "SELECT results, cached_at FROM cse_cache WHERE query_hash = ?", (h,)
            ).fetchone()

        if row is None:
            return None
        results_json, cached_at = row
        if cached_at < cutoff:
            return None

        return json.loads(results_json)

    def set(self, query: str, items: list[dict]) -> None:
        h = self._hash(query)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cse_cache (query_hash, query, results, cached_at) VALUES (?, ?, ?, ?)",
                (h, query, json.dumps(items), time.time()),
            )

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM cse_cache").fetchone()[0]
            fresh = conn.execute(
                "SELECT COUNT(*) FROM cse_cache WHERE cached_at > ?",
                (time.time() - self._ttl_seconds,),
            ).fetchone()[0]
        return {"total_entries": total, "fresh_entries": fresh}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    @staticmethod
    def _hash(query: str) -> str:
        return hashlib.sha256(query.encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL ENRICHER  — Finds founder and lead emails (Fix 5)
# ══════════════════════════════════════════════════════════════════════════════

class EmailEnricher:
    """
    Finds founder emails using:
    1. Hunter.io API (free tier: 25 searches/month)
    2. Pattern guessing (firstname@company.com, etc.)
    3. Brave search: '"firstname lastname" "@sarvam.ai"'
    """
    
    _log = logging.getLogger("pipeline.EmailEnricher")
    
    COMMON_PATTERNS = [
        "{first}@{domain}",
        "{first}.{last}@{domain}",
        "{first}{last}@{domain}",
        "{f}{last}@{domain}",
    ]

    def __init__(self) -> None:
        self.hunter_api_key = CFG.HUNTER_API_KEY if hasattr(CFG, "HUNTER_API_KEY") else os.environ.get("HUNTER_API_KEY", "")

    def find_email(self, contact_name: str, company_name: str, company_url: str = "") -> str:
        """
        Main interface to enrich a contact with an email.
        """
        domain = self._resolve_domain(company_name, company_url)
        if not domain:
            self._log.debug(f"Could not resolve domain for {company_name!r}")
            return ""

        parts = contact_name.lower().strip().split()
        if not parts:
            return ""
        first = parts[0]
        last = parts[-1] if len(parts) > 1 else ""
        f = first[0] if first else ""

        # 1. Try Hunter.io API
        if self.hunter_api_key:
            email = self._query_hunter(first, last, domain)
            if email:
                self._log.info(f"📧 [Hunter.io] Found email for {contact_name!r} at {company_name!r}: {email}")
                return email

        # 2. Try Brave Search pattern finding
        email = self._query_brave_for_email(contact_name, domain)
        if email:
            self._log.info(f"📧 [Brave Search] Found email for {contact_name!r} at {company_name!r}: {email}")
            return email

        # 3. Pattern Guessing
        guessed = self._guess_email(first, last, f, domain)
        if guessed:
            self._log.debug(f"📧 [Guessed] Email pattern for {contact_name!r} at {company_name!r}: {guessed}")
            return guessed

        return ""

    def _resolve_domain(self, company_name: str, company_url: str = "") -> str | None:
        from urllib.parse import urlparse
        
        # Heuristic 1: Extract from company_url if it's a direct website
        if company_url and not any(x in company_url.lower() for x in ["ycombinator.com", "wellfound.com", "yourstory.com", "inc42.com"]):
            try:
                parsed = urlparse(company_url)
                domain = parsed.netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                if domain:
                    return domain
            except Exception:
                pass

        # Heuristic 2: Use Brave Search to find the official website domain
        if not CFG.BRAVE_API_KEY:
            clean = company_name.lower().replace(" ", "").replace("pvt", "").replace("ltd", "").replace("inc", "").strip()
            return f"{clean}.ai"

        clean_name = company_name.replace(" pvt ltd", "").replace(" ltd", "").replace(" inc", "").replace(" co", "").strip()
        headers = {"Accept": "application/json", "X-Subscription-Token": CFG.BRAVE_API_KEY}
        params = {"q": f"{clean_name} startup official website", "count": 3}
        try:
            resp = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=8)
            if resp.status_code == 200:
                results = resp.json().get("web", {}).get("results", [])
                for r in results:
                    url = r.get("url", "")
                    if url and not any(x in url.lower() for x in [
                        "ycombinator.com", "wellfound.com", "yourstory.com", "inc42.com",
                        "linkedin.com", "twitter.com", "x.com", "github.com", "facebook.com",
                        "crunchbase.com", "youtube.com", "wikipedia.org", "medium.com"
                    ]):
                        parsed = urlparse(url)
                        domain = parsed.netloc.lower()
                        if domain.startswith("www."):
                            domain = domain[4:]
                        if domain:
                            return domain
        except Exception as e:
            self._log.debug(f"Error resolving domain via Brave: {e}")

        # Final fallback: Smart curated mapping & DNS/socket TLD verification
        # This completely resolves "Mad Street Den" guessing "madstreetden.ai" (which fails DNS)
        # and heals it to "madstreetden.com" (which resolves successfully!).
        clean = company_name.lower().replace(" ", "").replace("pvt", "").replace("ltd", "").replace("inc", "").strip()
        
        CURATED_DOMAINS = {
            "mad street den": "madstreetden.com",
            "sarvam": "sarvam.ai",
            "sarvam ai": "sarvam.ai",
            "krutrim": "krutrim.ai",
            "krutrim ai": "krutrim.ai",
            "ola krutrim": "krutrim.ai",
            "senseforth": "senseforth.com",
            "sigmoid": "sigmoid.com",
            "artivatic": "artivatic.ai",
            "artivatic data labs": "artivatic.ai",
            "arya": "arya.ai",
            "arya ai": "arya.ai",
        }
        
        if clean in CURATED_DOMAINS:
            self._log.debug(f"🌐 Curated domain mapping hit: {company_name!r} -> '{CURATED_DOMAINS[clean]}'")
            return CURATED_DOMAINS[clean]
            
        import socket
        tlds = [".com", ".ai", ".in", ".co", ".io"]
        for tld in tlds:
            test_domain = f"{clean}{tld}"
            try:
                socket.gethostbyname(test_domain)
                self._log.debug(f"🌐 Smart DNS resolution succeeded for fallback: {test_domain}")
                return test_domain
            except Exception:
                continue
                
        return f"{clean}.com"

    def _query_hunter(self, first: str, last: str, domain: str) -> str | None:
        url = "https://api.hunter.io/v2/email-finder"
        params = {
            "domain": domain,
            "first_name": first,
            "last_name": last,
            "api_key": self.hunter_api_key
        }
        try:
            resp = requests.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                email = data.get("email")
                score = data.get("score", 0)
                if email and score >= 60:
                    return email
        except Exception as e:
            self._log.debug(f"Hunter.io lookup failed: {e}")
        return None

    def _query_brave_for_email(self, contact_name: str, domain: str) -> str | None:
        if not CFG.BRAVE_API_KEY:
            return None
        q = f'"{contact_name}" "@{domain}"'
        headers = {"Accept": "application/json", "X-Subscription-Token": CFG.BRAVE_API_KEY}
        params = {"q": q, "count": 3}
        try:
            resp = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=8)
            if resp.status_code == 200:
                results = resp.json().get("web", {}).get("results", [])
                email_regex = re.compile(rf"[a-zA-Z0-9._%+-]+@{re.escape(domain)}", re.IGNORECASE)
                for r in results:
                    snippet = r.get("description", "") + " " + r.get("title", "")
                    matches = email_regex.findall(snippet)
                    if matches:
                        return matches[0].lower().strip()
        except Exception as e:
            self._log.debug(f"Brave Search email scraping failed: {e}")
        return None

    def _guess_email(self, first: str, last: str, f: str, domain: str) -> str | None:
        if not first or not domain:
            return None
        return f"{first}@{domain}"


# ══════════════════════════════════════════════════════════════════════════════
#  ENRICHER  — DO NOT TOUCH core logic; unchanged from v3
# ══════════════════════════════════════════════════════════════════════════════

class Enricher:
    """
    Enriches each company with LinkedIn contacts via Brave Search API.
    hiring_signal drives the CSE query strategy (unchanged from v3).
    _build_queries() always returns exactly 3 keys = 3 Brave calls per company.
    """

    _log = logging.getLogger("pipeline.Enricher")
    _BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    _SUFFIX_PATTERN = re.compile(
        r"(?i)\b(inc|llc|ltd|pvt|private|corporation|corp|"
        r"technologies|technology|tech|labs|solutions|ventures|group)\b\.?",
    )

    def __init__(self) -> None:
        self._cache = QueryCache()
        self.total_api_calls = 0
        self.queries_by_source = {
            "funding":   0,
            "yc":        0,
            "yourstory": 0,
            "instahyre": 0,
            "wellfound": 0,
            "linkedin":  0,
        }
        self.source_caps = {
            "funding":    55,
            "yc":         45,
            "yourstory":  40,
            "instahyre":  35,   # Upgrade #3
            "naukri":     30,   # Upgrade #3
            "jobcode18":  30,   # Upgrade #5
            "wellfound":  25,
            "linkedin":   20,
        }


    def _get_allowed_angles_and_queries(self, source: str) -> list[str]:
        source_key = source.lower().strip()
        # Tier 1: YC + Funding -> Tech Leads, Senior Tech Leads, Founders/Leadership (3 queries)
        if source_key in ("yc", "funding"):
            return ["Technical Leads", "Senior Technical Leads", "Founders/Leadership"]
        # Tier 2: Wellfound + YourStory -> Tech Leads, HR/Recruiting (2 queries)
        if source_key in ("wellfound", "yourstory"):
            return ["Technical Leads", "HR/Recruiting"]
        # Tier 3 & 4: Instahyre + LinkedIn -> Technical Leads (1 query)
        return ["Technical Leads"]

    def run(self, companies: list[Company]) -> list[Contact]:
        self._log.info("━━━━  PHASE 2 : Enricher (Brave Search + Cache)  ━━━━")

        cache_stats = self._cache.stats()
        self._log.info(
            f"  Cache: {cache_stats['fresh_entries']} fresh / {cache_stats['total_entries']} total"
        )

        seen_co:    set[str] = set()
        unique_cos: list[Company] = []
        for c in companies:
            key = normalize_company_name(c["name"])
            if key not in seen_co:
                seen_co.add(key)
                unique_cos.append(c)

        self._log.info(f"  Unique companies to enrich: {len(unique_cos)}")

        all_contacts:    list[Contact] = []
        total_accepted   = 0
        total_filtered   = 0
        total_cache_hits = 0
        quota_exceeded   = False

        # Reset query tracking counters for this run
        self.total_api_calls = 0
        for k in self.queries_by_source:
            self.queries_by_source[k] = 0

        try:
            for idx, company in enumerate(unique_cos, start=1):
                if quota_exceeded:
                    self._log.warning("  🚫  Quota hit — halting enrichment.")
                    break

                if self.total_api_calls >= 240:
                    self._log.warning("  🚫  Hard query cap of 240 reached — halting enrichment to protect Brave monthly quota.")
                    quota_exceeded = True
                    break

                signal_icon = {
                    "job_post": "📋", "yc_batch": "🚀",
                    "launch": "🚀", "funding": "💰",
                }.get(company["hiring_signal"], "🔍")
                self._log.info(
                    f"  {signal_icon}  [{idx}/{len(unique_cos)}]  "
                    f"{company['name']!r}  [{company['hiring_signal']}]"
                )

                try:
                    contacts, accepted, filtered, api_calls, cache_hits, hit_quota = (
                        self._enrich_company(company)
                    )
                    all_contacts.extend(contacts)
                    total_accepted   += accepted
                    total_filtered   += filtered
                    total_cache_hits += cache_hits
                    if hit_quota or self.total_api_calls >= 240:
                        quota_exceeded = True

                except Exception as exc:
                    self._log.error(
                        f"  ❌  Enrichment failed for {company['name']!r}: {exc}\n"
                        + traceback.format_exc(limit=3)
                    )
        finally:
            pass

        self._log.info(
            f"✅  Enricher complete — "
            f"accepted={total_accepted}, filtered={total_filtered}, "
            f"api_calls={self.total_api_calls}, cache_hits={total_cache_hits}, "
            f"total_contacts={len(all_contacts)}"
        )
        return all_contacts

    def _enrich_company(
        self,
        company: Company,
    ) -> tuple[list[Contact], int, int, int, int, bool]:
        company_clean   = self._clean_company_name(company["name"])
        target_keywords = get_dynamic_keywords_for_company(company)
        seen_urls:  set[str] = set()
        contacts:   list[Contact] = []
        accepted = filtered = api_calls = cache_hits = 0
        quota_hit = False

        queries = self._build_queries(company_clean, company["hiring_signal"])

        # Track if company size is detected to be >= 50 employees (Fix 3)
        is_50_plus = False

        src = company.get("source", "funding").lower().strip()
        allowed_angles = self._get_allowed_angles_and_queries(src)

        for angle in allowed_angles:
            if angle not in queries:
                continue

            query = queries[angle]

            # If we detected 50+ employees and this is the Founders query, pivot!
            if is_50_plus and angle == "Founders/Leadership":
                angle = "Engineering Managers"
                safe_name = company_clean.replace('"', '').strip()
                loc_suffix = 'India ("Bengaluru" OR "Bangalore" OR "Hyderabad" OR "Mumbai" OR "Pune" OR "Gurgaon" OR "Gurugram" OR "Noida" OR "Delhi" OR "NCR" OR "Chennai")'
                query = (
                    f'site:linkedin.com/in "{safe_name}" '
                    f'("Engineering Manager" OR "Team Lead" OR "Staff Engineer") {loc_suffix}'
                )
                self._log.info(f"      ➔ Pivot: Company size detected >= 50 employees. Swapping Founders query for Engineering Managers.")

            self._log.debug(f"    [{angle}]: {query[:80]}…")

            # Check source-specific query limits
            current_src_queries = self.queries_by_source.get(src, 0)
            src_cap = self.source_caps.get(src, 30)

            cached_items = self._cache.get(query)
            if cached_items is not None:
                items = cached_items
                cache_hits += 1
            else:
                # If we've reached the overall query cap or this source's query cap, skip
                if self.total_api_calls >= 240:
                    self._log.warning("      ✕ Skipping query: hard query cap of 240 reached.")
                    continue

                if current_src_queries >= src_cap:
                    self._log.info(f"      ✕ Skipping live search: reached cap of {src_cap} queries for source '{src}'.")
                    continue

                items, did_hit_quota = self._execute_query_with_retry(query)
                api_calls += 1
                self.total_api_calls += 1
                self.queries_by_source[src] = current_src_queries + 1

                if did_hit_quota:
                    quota_hit = True
                    break

                if items is not None:
                    self._cache.set(query, items)
                else:
                    items = []

            for item in items:
                url = _strip_tracking(item.get("link", ""))

                if "linkedin.com/in/" not in url.lower():
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                name, title = Scorer.parse_profile_title(item.get("title", ""))
                snippet     = item.get("snippet", "")

                # Snippet freshness precheck to prevent wasting selenium and account risk
                if not verify_linkedin_freshness_via_snippet(item.get("title", ""), snippet, company["name"], self._log):
                    filtered += 1
                    continue

                # Skip contacts from massive companies based on employee counts in search snippet (Fix 2 & TARGET_COMPANY_CRITERIA)
                large_size_indicators = (
                    "201-500", "501-1,000", "1,001-5,000", "5,001-10,000", "10,001+", 
                    "200+ employees", "500+ employees", "1000+ employees", "5000+ employees", 
                    "10000+ employees", "10,001", "5,001", "10001", "5001"
                )
                if any(x in snippet for x in large_size_indicators):
                    self._log.debug(f"    ✕ Skipping massive/mid-large company contact '{name}' based on snippet employee count.")
                    filtered += 1
                    continue

                # Check snippet for company size indicators >= 50 employees (Fix 3)
                _50_PLUS_INDICATORS = ("51-200", "50+", "50+ employees", "100+ employees")
                if any(x in snippet for x in _50_PLUS_INDICATORS):
                    is_50_plus = True

                score       = Scorer.calculate_relevance_score(
                    name, title, snippet, company_clean, target_keywords
                )

                if score >= CFG.MIN_RELEVANCE_SCORE:
                    contacts.append(Contact(
                        source_company  = company["name"],
                        contact_name    = name,
                        contact_title   = title,
                        linkedin_url    = url,
                        relevance_score = score,
                    ))
                    accepted += 1
                else:
                    filtered += 1

            if not quota_hit:
                time.sleep(CFG.API_DELAY_S)

        contacts.sort(key=lambda c: c["relevance_score"], reverse=True)

        # Select fresh contacts purely from parsed, snippet-verified results (saves 40+ mins/run & avoids login/CAPTCHA risk)
        fresh_contacts = contacts[:CFG.CONTACTS_PER_COMPANY]

        # Enrich fresh contacts with founder/lead email addresses
        email_enricher = EmailEnricher()
        for contact in fresh_contacts:
            email = email_enricher.find_email(contact["contact_name"], company["name"], company.get("source_url", ""))
            contact["email"] = email

        self._log.info(
            f"      accepted={accepted}, filtered={filtered}, "
            f"api={api_calls}, cache={cache_hits}, kept={len(fresh_contacts)}"
        )
        return fresh_contacts, accepted, filtered, api_calls, cache_hits, quota_hit


    def _build_queries(self, company_clean: str, hiring_signal: str) -> dict[str, str]:
        """
        Build 3 search queries tuned to the hiring signal.
        Always returns exactly 3 keys (= 3 Brave API calls per company).
        DO NOT MODIFY — agreed quota allocation depends on this being exactly 3.
        """
        safe_name = company_clean.replace('"', '').strip()

        # Force India & major metropolitan startup hubs to prevent wasting Brave Search quota on international profiles
        loc_suffix = 'India ("Bengaluru" OR "Bangalore" OR "Hyderabad" OR "Mumbai" OR "Pune" OR "Gurgaon" OR "Gurugram" OR "Noida" OR "Delhi" OR "NCR" OR "Chennai")'

        founder_q = (
            f'site:linkedin.com/in "{safe_name}" '
            f'(Founder OR "Co-founder" OR CEO OR CTO) {loc_suffix}'
        )
        hr_q = (
            f'site:linkedin.com/in "{safe_name}" '
            f'(Recruiter OR "Talent Acquisition" OR Hiring OR HR) {loc_suffix}'
        )
        tech_q = (
            f'site:linkedin.com/in "{safe_name}" '
            f'("AI Engineer" OR "ML Engineer" OR "Machine Learning" '
            f'OR "Data Scientist" OR MLOps OR "Tech Lead") {loc_suffix}'
        )
        senior_tech_q = (
            f'site:linkedin.com/in "{safe_name}" '
            f'("Staff Engineer" OR "Principal Engineer" OR Architect OR "Tech Lead" OR "Lead Engineer") {loc_suffix}'
        )

        if hiring_signal == "funding":
            return {
                "Technical Leads":         tech_q,
                "Senior Technical Leads":  senior_tech_q,
                "Founders/Leadership":     founder_q,
            }

        if hiring_signal == "yc_batch":
            return {
                "Technical Leads":         tech_q,
                "Senior Technical Leads":  senior_tech_q,
                "Founders/Leadership":     founder_q,
            }

        if hiring_signal == "launch":
            return {
                "Technical Leads":         tech_q,
                "Senior Technical Leads":  senior_tech_q,
                "Founders/Leadership":     founder_q,
            }

        # job_post (Wellfound) — larger company with an actual recruiter worth finding.
        return {
            "HR/Recruiting":       hr_q,
            "Technical Leads":     tech_q,
            "Founders/Leadership": founder_q,
        }

    def _execute_query_with_retry(self, query: str) -> tuple[list[dict], bool]:
        """
        Executes a query using Brave Search API.
        DO NOT MODIFY — this is the only quota resource in the pipeline.
        """
        if not CFG.BRAVE_API_KEY:
            self._log.error("BRAVE_API_KEY is not set in .env")
            return None, False

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": CFG.BRAVE_API_KEY
        }
        params = {
            "q": query,
            "count": CFG.CSE_RESULTS_PER_QUERY,
            "safesearch": "off"
        }

        for attempt in range(CFG.MAX_RETRIES):
            try:
                resp = requests.get(self._BRAVE_ENDPOINT, headers=headers, params=params, timeout=12)

                if resp.status_code == 429:
                    self._log.warning("  ⚠  HTTP 429 — Brave API rate limit hit.")
                    return [], True

                resp.raise_for_status()
                data = resp.json()

                raw_results = data.get("web", {}).get("results", [])
                items = []
                for r in raw_results:
                    items.append({
                        "link": r.get("url"),
                        "title": r.get("title"),
                        "snippet": r.get("description")
                    })

                return items, False

            except requests.exceptions.Timeout:
                jitter    = random.uniform(0.2, 1.2)
                sleep_for = (CFG.BACKOFF_BASE_S ** attempt) + jitter
                self._log.warning(f"  ⚠  Timeout (attempt {attempt + 1}/{CFG.MAX_RETRIES}) — retry in {sleep_for:.1f}s…")
                time.sleep(sleep_for)

            except requests.exceptions.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if 400 <= code < 500:
                    self._log.error(f"  ❌  HTTP {code} — not retrying.")
                    return None, False
                jitter    = random.uniform(0.2, 1.2)
                sleep_for = (CFG.BACKOFF_BASE_S ** attempt) + jitter
                self._log.warning(f"  ⚠  HTTP {code} (attempt {attempt + 1}) — retry in {sleep_for:.1f}s…")
                time.sleep(sleep_for)

            except requests.exceptions.RequestException as exc:
                self._log.error(f"  ❌  Network error: {exc}")
                break

        self._log.error(f"  ❌  All {CFG.MAX_RETRIES} retries exhausted.")
        return None, False

    @classmethod
    def _clean_company_name(cls, name: str) -> str:
        name = re.sub(r"\(.*?\)", "", name)
        name = cls._SUFFIX_PATTERN.sub("", name)
        name = re.sub(r"[,:\-]+$", "", name).strip()
        return name


# ══════════════════════════════════════════════════════════════════════════════
#  KEYWORD HELPERS  (unchanged from v3 — DO NOT TOUCH)
# ══════════════════════════════════════════════════════════════════════════════

def get_dynamic_keywords_for_company(company: Company) -> list[str]:
    """
    Maps a Company to role-aware LinkedIn target keywords.
    Uses hiring_signal as the primary signal when no job_title exists.
    """
    baseline: list[str] = [
        "founder", "co-founder", "ceo", "cto",
        "recruiter", "talent acquisition", "hiring manager",
    ]

    if company.get("job_title"):
        return get_dynamic_keywords(company["job_title"])

    if company["hiring_signal"] == "funding":
        return baseline + [
            "head of engineering", "vp engineering", "engineering lead",
            "ai lead", "ml lead", "data lead", "technical lead",
        ]

    if company["hiring_signal"] == "yc_batch":
        return baseline + [
            "ai engineer", "machine learning", "data scientist",
            "head of engineering", "senior engineer",
        ]

    if company["hiring_signal"] == "launch":
        return baseline + [
            "ai engineer", "ml engineer", "full stack", "backend engineer",
            "platform engineer", "tech lead",
        ]

    return baseline + ["ai engineer", "machine learning", "data scientist"]


def get_dynamic_keywords(job_title: str) -> list[str]:
    """v2 job-title-based keywords — preserved exactly."""
    baseline: list[str] = [
        "founder", "co-founder", "ceo", "cto",
        "recruiter", "talent acquisition", "hiring manager",
    ]
    t = job_title.lower()

    if any(x in t for x in ("mlops", "ml ops", "platform", "infrastructure")):
        return baseline + ["mlops", "ml platform", "infrastructure lead", "head of platform"]
    if any(x in t for x in ("data scientist", "data science")):
        return baseline + ["data scientist", "head of data", "analytics lead", "ai researcher"]
    if "data engineer" in t:
        return baseline + ["data engineer", "data architecture", "etl", "data infrastructure"]
    if "data analyst" in t:
        return baseline + ["data analyst", "analytics", "business intelligence", "bi lead"]

    return baseline + [
        "ai engineer", "machine learning", "ai lead",
        "head of engineering", "senior ml engineer",
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  WRITER  (unchanged from v3 — DO NOT TOUCH)
# ══════════════════════════════════════════════════════════════════════════════

SHEET_HEADERS: list[str] = [
    "Company",
    "Source",
    "Hiring Signal",
    "Wellfound Role",
    "Urgency",
    "Contact Name",
    "Contact Title",
    "LinkedIn URL",
    "Relevance Score",
    "Date Added",
    "Status",
    "Company Description",
    "Email",
    "Careers URL",       # CareerPortalFinder — direct Greenhouse/Lever/Workable/Ashby link
    "Wellfound URL",     # CareerPortalFinder — 1-click Wellfound apply
    "Naukri URL",        # CareerPortalFinder — reference
    "Instahyre URL",     # CareerPortalFinder — reference
]


class Writer:
    """
    Consolidates Company + Contact data and writes to Google Sheets.
    Unchanged from v3.
    """

    _log = logging.getLogger("pipeline.Writer")

    def consolidate(self, companies: list[Company], contacts: list[Contact]) -> pd.DataFrame:
        if not companies:
            self._log.warning("No companies to consolidate — returning empty DataFrame.")
            return pd.DataFrame()

        today        = _today_str()
        companies_df = pd.DataFrame(companies)

        if not contacts:
            self._log.warning("No contacts — writing company-only rows.")
            companies_df["contact_name"]    = ""
            companies_df["contact_title"]   = ""
            companies_df["linkedin_url"]    = ""
            companies_df["relevance_score"] = 0
            companies_df["date_added"]      = today
            companies_df["status"]          = "Pending"
            return self._reorder_and_sort(companies_df)

        contacts_df = pd.DataFrame(contacts)

        companies_df["_key"] = companies_df["name"].str.lower().str.strip()
        contacts_df["_key"]  = contacts_df["source_company"].str.lower().str.strip()

        merged = pd.merge(
            companies_df,
            contacts_df.drop(columns=["source_company"]),
            on="_key",
            how="left",
        ).drop(columns=["_key"])

        merged["date_added"]      = today
        merged["status"]          = "Pending"
        merged["relevance_score"] = merged["relevance_score"].fillna(0).astype(int)

        final = self._reorder_and_sort(merged)
        self._log.info(
            f"  Consolidated: {len(companies)} companies × {len(contacts)} contacts → {len(final)} rows"
        )
        return final

    def write_to_sheet(self, df: pd.DataFrame) -> int:
        if df.empty:
            self._log.warning("DataFrame is empty — nothing to write.")
            return 0

        if not os.path.exists(CFG.GOOGLE_CREDENTIALS_FILE):
            raise FileNotFoundError(
                f"Service account key not found: '{CFG.GOOGLE_CREDENTIALS_FILE}'"
            )
        creds = GCredentials.from_service_account_file(
            CFG.GOOGLE_CREDENTIALS_FILE,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc = gspread.authorize(creds)

        try:
            sh = gc.open(CFG.GOOGLE_SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(CFG.GOOGLE_SHEET_NAME)
            self._log.info(f"  Created new spreadsheet: {CFG.GOOGLE_SHEET_NAME!r}")

        # Seed existing_urls by reading column 8 (H) of all existing worksheets in this spreadsheet
        existing_urls: set[str] = set()
        try:
            worksheets = sh.worksheets()
            for ws in worksheets:
                # Skip the "IITK Alumni" tab as it has different columns
                if ws.title == "IITK Alumni":
                    continue
                # Read all values from column 8 (LinkedIn URL)
                col_vals = ws.col_values(8)
                for val in col_vals:
                    val_clean = str(val).strip()
                    if val_clean and val_clean.startswith("http"):
                        existing_urls.add(val_clean)
            self._log.info(f"  Loaded {len(existing_urls)} existing LinkedIn URLs from Google Sheets to prevent duplicates.")
        except Exception as e:
            self._log.warning(f"  Could not load existing URLs from Google Sheets: {e}")

        # Now create the new worksheet for this run
        timestamp  = datetime.now().strftime("%Y-%m-%d_%H%M")
        sheet_name = f"Leads_{timestamp}"
        sheet      = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
        self._log.info(f"  Created new worksheet: {sheet_name!r}")

        sheet.append_row(SHEET_HEADERS)
        self._log.info("  Sheet headers initialised.")

        new_rows:  list[list[str]] = []
        duplicates = 0
        today = _today_str()

        for _, row in df.iterrows():
            url = str(row.get("linkedin_url", "")).strip()
            if url and url in existing_urls:
                duplicates += 1
                continue

            new_rows.append([
                str(row.get("name",            "")),
                str(row.get("source",          "wellfound")),
                str(row.get("hiring_signal",   "job_post")),
                str(row.get("job_title",       "")),
                str(row.get("urgency",         "3 - Standard (Actively Hiring)")),
                str(row.get("contact_name",    "")),
                str(row.get("contact_title",   "")),
                url,
                str(row.get("relevance_score", 0)),
                str(row.get("date_added",      today)),
                str(row.get("status",          "Pending")),
                str(row.get("company_description", "")),
                str(row.get("email",           "")),
                str(row.get("careers_url",     "")),
                str(row.get("wellfound_url",   "")),
                str(row.get("naukri_url",      "")),
                str(row.get("instahyre_url",   "")),
            ])
            if url:
                existing_urls.add(url)

        if new_rows:
            for i in range(0, len(new_rows), 100):
                sheet.append_rows(new_rows[i : i + 100], value_input_option="USER_ENTERED")
                time.sleep(1.0)
            self._log.info(f"✅  Wrote {len(new_rows)} new rows ({duplicates} duplicates skipped).")
        else:
            self._log.info(f"  Nothing new to write ({duplicates} duplicates skipped).")

        return len(new_rows)

    @staticmethod
    def _reorder_and_sort(df: pd.DataFrame) -> pd.DataFrame:
        col_order = [
            "name", "source", "hiring_signal", "job_title", "urgency",
            "contact_name", "contact_title", "linkedin_url",
            "relevance_score", "date_added", "status", "company_description",
            "email",
            "careers_url", "wellfound_url", "naukri_url", "instahyre_url",
        ]
        for col in col_order:
            if col not in df.columns:
                df[col] = ""
        df = df[col_order].fillna("")
        return df.sort_values(
            by=["urgency", "relevance_score"],
            ascending=[True, False],
        ).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def _generate_env_template() -> None:
    template = """\
# ─────────────────────────────────────────────────────────────────────────────
# Startup Opportunity Discovery Engine v4 — Environment Variables
# Copy this file to .env and fill in your values. NEVER commit .env to git.
# ─────────────────────────────────────────────────────────────────────────────

# Brave Search API (only paid API used — 1,000 free queries/month)
BRAVE_API_KEY=your_brave_api_key_here

# Hunter.io API (free tier: 25 searches/month) for founder email verification
HUNTER_API_KEY=your_hunter_api_key_here

# Google Sheets credentials
GOOGLE_CREDENTIALS_FILE=google_creds.json
GOOGLE_SHEET_NAME=Job Pipeline Leads

# Which sources to run: all | wellfound | yc | yourstory | funding
# Use comma-separated values to run a subset: wellfound,yc
# Default: all (recommended for full coverage)
ACTIVE_SOURCES=all

# Brave Profile Path (for Wellfound scraping — only this source needs login)
BRAVE_PROFILE_PATH="/home/youruser/.config/BraveSoftware/Brave-Browser-Beta/Default"

# Set to 1 to enable verbose DEBUG logging
PIPELINE_DEBUG=
"""
    with open(".env.example", "w") as f:
        f.write(template)
    print("✅  .env.example written.")
    print("\nNext steps:")
    print("  1.  cp .env.example .env")
    print("  2.  nano .env")
    print("  3.  echo '.env' >> .gitignore")
    print("  4.  python job_pipeline_v2.py")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Startup Opportunity Discovery Engine v4 — India-Focused"
    )
    parser.add_argument("--setup", action="store_true",
                        help="Generate a .env.example template and exit")
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose DEBUG output")
    parser.add_argument(
        "--sources",
        metavar="SOURCES",
        default=None,
        help="Comma-separated source names: wellfound,yc,yourstory,funding,instahyre,naukri,jobcode18",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help=(
            "Delete all cached Brave Search results before running. "
            "Use this if you want fresh results."
        ),
    )
    parser.add_argument(
        "--morning",
        action="store_true",
        help=(
            "Master morning run: discovery + enrichment + auto-apply to careers pages "
            "+ send cold emails + send follow-ups. "
            "Equivalent to: pipeline → auto_applier.py → outreach_engine.py --send-emails --send-followups"
        ),
    )
    return parser.parse_args()


def _preflight() -> None:
    errors: list[str] = []

    if not CFG.BRAVE_API_KEY:
        errors.append(
            "BRAVE_API_KEY is not set.\n"
            "  → Register at api.search.brave.com and add BRAVE_API_KEY to your .env"
        )
    if not os.path.exists(CFG.GOOGLE_CREDENTIALS_FILE):
        errors.append(
            f"GOOGLE_CREDENTIALS_FILE '{CFG.GOOGLE_CREDENTIALS_FILE}' not found.\n"
            "  → GCP Console → IAM → Service Accounts → Keys → Add Key → JSON"
        )

    if errors:
        LOG.error("Pre-flight failed — missing credentials:\n")
        for i, msg in enumerate(errors, 1):
            LOG.error(f"  [{i}] {msg}\n")
        LOG.error("Run  python job_pipeline_v2.py --setup  to generate a .env template.")
        sys.exit(1)

    LOG.info("✅  Pre-flight checks passed.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR  (P3, P4, P5, P8 integrated here)
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    args = _parse_args()

    if args.setup:
        _generate_env_template()
        return

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for h in logging.getLogger().handlers:
            h.setLevel(logging.DEBUG)

    if args.clear_cache:
        db_path = CFG.CACHE_DB_PATH
        if os.path.exists(db_path):
            conn    = sqlite3.connect(db_path)
            deleted = conn.execute("DELETE FROM cse_cache").rowcount
            conn.commit()
            conn.close()
            LOG.info(f"🗑  Cache cleared — {deleted} entries deleted from {db_path}")
        else:
            LOG.info("  Cache DB not found — nothing to clear.")

    sep = "═" * 68
    LOG.info(sep)
    LOG.info("  Startup Opportunity Discovery Engine  —  v4  (India-Focused)")
    LOG.info(f"  Started : {datetime.today().strftime('%Y-%m-%d %H:%M:%S')}")
    LOG.info(sep)

    _preflight()

    active_sources = args.sources if args.sources else CFG.ACTIVE_SOURCES

    try:
        # ── Phase 1: Multi-source discovery ───────────────────────────────────
        collector = MultiSourceCollector(active_sources=active_sources)
        companies = collector.run()

        if not companies:
            LOG.error("All sources returned 0 companies. Check your network and selectors.")
            sys.exit(1)

        LOG.info(f"  Phase 1 complete — {len(companies)} unique companies discovered")

        # ── P4: Cross-run deduplication (14-day window) ────────────────────────
        seen_cache = SeenCompaniesCache()
        companies  = seen_cache.filter_new(companies)

        if not companies:
            LOG.warning("  All companies were seen in the last 14 days — nothing new to enrich.")
            LOG.warning("  Skipping enrichment and moving to IITK Alumni module.")
            companies_to_enrich = []
            contacts = []
            written = 0
        else:
            # ── P5: Relevance pre-filter ───────────────────────────────────────────
            before_filter = len(companies)
            companies     = [c for c in companies if _passes_relevance_filter(c)]
            dropped_irrel = before_filter - len(companies)
            if dropped_irrel:
                LOG.info(
                    f"  Relevance filter: dropped {dropped_irrel} companies "
                    f"with no AI/ML keywords (saved {dropped_irrel * 3} Brave queries)"
                )

            if not companies:
                LOG.warning("  No companies passed the relevance filter.")
                companies_to_enrich = []
                contacts = []
                written = 0
            else:
                # ── P3: Cap enrichment to top MAX_COMPANIES_TO_ENRICH ─────
                # Priority: Wellfound (0) > YC (1) > Others
                source_priority = {"wellfound": 0, "yc": 1, "yourstory": 2, "funding": 3}
                companies_sorted = sorted(
                    companies,
                    key=lambda c: source_priority.get(c["source"], 9),
                )
                if len(companies_sorted) > CFG.MAX_COMPANIES_TO_ENRICH:
                    dropped_cap       = len(companies_sorted) - CFG.MAX_COMPANIES_TO_ENRICH
                    companies_to_enrich = companies_sorted[: CFG.MAX_COMPANIES_TO_ENRICH]
                    LOG.info(
                        f"  Capped enrichment at {CFG.MAX_COMPANIES_TO_ENRICH} — "
                        f"dropped {dropped_cap} lower-priority companies"
                    )
                else:
                    companies_to_enrich = companies_sorted

                # ── Phase 2: Enrich with LinkedIn contacts ────────────────────────────
                contacts = Enricher().run(companies_to_enrich)
                LOG.info(f"  Phase 2 complete — {len(contacts)} contacts found")

                # ── Phase 3: Consolidate and write to Google Sheets ───────────────────
                writer   = Writer()
                final_df = writer.consolidate(companies_to_enrich, contacts)
                LOG.info(f"  Phase 3 complete — {len(final_df)} consolidated rows")

                if not final_df.empty:
                    preview_cols = ["name", "source", "hiring_signal", "urgency",
                                    "contact_name", "relevance_score"]
                    available    = [c for c in preview_cols if c in final_df.columns]
                    LOG.info(
                        "\n  Top leads preview:\n"
                        + final_df[available].head(10).to_string(index=False)
                    )

                written = writer.write_to_sheet(final_df)

                # ── P4: Mark enriched companies as seen (only if write succeeded) ─────
                if written > 0:
                    seen_cache.mark_seen(companies_to_enrich)

                # ── Signal breakdown ──────────────────────────────────────────────────
                if not final_df.empty and "hiring_signal" in final_df.columns:
                    breakdown = final_df["hiring_signal"].value_counts()
                    LOG.info("\n  Companies by hiring signal:")
                    for signal, count in breakdown.items():
                        LOG.info(f"    {signal:<16} {count:>4}")

        # ── P8: IITK Alumni standalone module ─────────────────────────────────
        LOG.info("")
        LOG.info("  Running IITK Alumni module (8 queries, ~32/month budget)…")
        alumni_source = IITKAlumniSource()
        alumni        = alumni_source.run(companies=companies_to_enrich)
        alumni_source.write_to_sheet(alumni)

        # ── Final summary ─────────────────────────────────────────────────────
        LOG.info(sep)
        LOG.info("  ✓  Pipeline finished successfully")
        LOG.info(f"     Companies discovered  : {len(companies)}")
        LOG.info(f"     Companies enriched    : {len(companies_to_enrich)}")
        LOG.info(f"     Contacts found        : {len(contacts)}")
        LOG.info(f"     Rows written          : {written}")
        LOG.info(f"     IITK alumni found     : {len(alumni)}")
        LOG.info(f"     Active sources        : {active_sources}")
        LOG.info(f"     Cache DB              : {CFG.CACHE_DB_PATH}")
        LOG.info(sep)
        LOG.info("")
        LOG.info("  NEXT STEP: Run outreach_engine.py to generate your messages.")
        LOG.info("  Priority order: IITK Alumni → funding leads → yc_batch → job_post")
        LOG.info(sep)

        # ── --morning: chain auto-apply + email dispatch ─────────────────────
        if args.morning:
            import subprocess
            _python = sys.executable
            _base   = os.path.dirname(os.path.abspath(__file__))

            LOG.info("")
            LOG.info("━" * 68)
            LOG.info("  ››  --morning: Step 2/3 — CareersPageApplier (auto_applier.py)")
            LOG.info("━" * 68)
            subprocess.run(
                [_python, os.path.join(_base, "auto_applier.py"), "--limit", "10"],
                check=False,
            )

            LOG.info("")
            LOG.info("━" * 68)
            LOG.info("  ››  --morning: Step 3/3 — outreach_engine.py --send-emails --send-followups")
            LOG.info("━" * 68)
            subprocess.run(
                [_python, os.path.join(_base, "outreach_engine.py"),
                 "--send-emails", "--send-followups"],
                check=False,
            )

            LOG.info("")
            LOG.info("━" * 68)
            LOG.info("  ✓✓✓  Morning run complete. Check logs above for results.")
            LOG.info("━" * 68)


    except KeyboardInterrupt:
        LOG.warning("\n  ⚠  Interrupted by user — data gathered so far is saved.")
    except Exception as exc:
        LOG.critical(f"  Fatal unhandled error: {exc}")
        LOG.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()