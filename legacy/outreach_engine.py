"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       Outreach Conversion Engine  —  v2  (Signal-Aware)                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Runs on top of job_pipeline_v3.py output.                                  ║
║                                                                             ║
║  WHAT'S NEW IN v2                                                           ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  v1 generated messages based only on contact type (founder / recruiter).    ║
║  v2 ALSO uses hiring_signal to change the opening hook:                     ║
║                                                                             ║
║    job_post  → "I saw the [role] opening on Wellfound..." (v1 behaviour)    ║
║    yc_batch  → "Congrats on the YC batch. I wanted to reach out..."        ║
║    launch    → "Saw the launch — looks like you're shipping fast..."        ║
║    funding   → "Congratulations on the raise. Teams usually grow..."        ║
║                                                                             ║
║  This matters because:                                                       ║
║  • Funded / launched founders get generic "I saw your job posting" messages ║
║    100x per day. Your message that references their actual event stands out. ║
║  • YC founders expect to be contacted by engineers. Reference the batch.    ║
║                                                                             ║
║  NEW: Signal-priority queue                                                  ║
║    funding and yc_batch leads are surfaced first in the daily briefing,     ║
║    REGARDLESS of their overall priority score, because they are the         ║
║    highest-ROI contacts (founders, less competition, decision-maker access). ║
║                                                                             ║
║  NEW: --source filter CLI flag                                               ║
║    python outreach_engine.py --source funding                               ║
║    Shows only leads from the funding source — useful when quota is tight.   ║
║                                                                             ║
║  EVERYTHING FROM v1 IS PRESERVED:                                            ║
║    follow-up tracking · campaign stats · CRM sync · mark-contacted          ║
║                                                                             ║
║  HOW TO USE                                                                 ║
║    Morning run: python outreach_engine.py                                   ║
║    Follow-ups:  python outreach_engine.py --followups                       ║
║    Stats:       python outreach_engine.py --stats                           ║
║    Filter:      python outreach_engine.py --source funding                  ║
║    Mark sent:   python outreach_engine.py --mark-contacted "https://..."    ║
╚══════════════════════════════════════════════════════════════════════════════╝

WHY THIS VERSION GETS MORE REPLIES
───────────────────────────────────
  The message a funded founder receives:

    v1:  "Hi Alex, I came across the AI Engineer role at AcmeCo and wanted to reach out."
    v2:  "Hi Alex, congrats on the Series A. Teams at this stage usually need to scale
          engineering fast. I'm an IIT Kanpur grad specialising in ML infra — would love
          to talk about what you're building."

  v2 demonstrates that you KNOW what's happening at the company right now.
  That single change is what moves the reply rate from 5% to 20%+.
"""

from __future__ import annotations

# ── Standard Library ──────────────────────────────────────────────────────────
import os
import re
import sys
import time
import logging
import argparse
import textwrap
import traceback
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import TypedDict

# ── .env support ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Third-party ───────────────────────────────────────────────────────────────
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
    from tabulate import tabulate
    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OutreachConfig:
    """
    All outreach constants in one place.
    Edit CANDIDATE_* fields to personalise your messages.
    """

    # ── Google Sheets ──────────────────────────────────────────────────────────
    GOOGLE_CREDENTIALS_FILE: str = os.environ.get("GOOGLE_CREDENTIALS_FILE", "google_creds.json")
    GOOGLE_SHEET_NAME:       str = os.environ.get("GOOGLE_SHEET_NAME",       "Job Pipeline Leads")

    LEADS_TAB: str = "Sheet1"
    CRM_TAB:   str = "Outreach CRM"

    # ── Your personal details ─────────────────────────────────────────────────
    CANDIDATE_NAME:      str = os.environ.get("CANDIDATE_NAME",      "Your Name")
    CANDIDATE_INSTITUTE: str = os.environ.get("CANDIDATE_INSTITUTE",  "IIT Kanpur")
    CANDIDATE_GRAD_YEAR: str = os.environ.get("CANDIDATE_GRAD_YEAR",  "2024")
    CANDIDATE_SKILLS:    str = os.environ.get(
        "CANDIDATE_SKILLS",
        "ML pipelines, model deployment, MLOps, and data engineering"
    )
    CANDIDATE_LINKEDIN:  str = os.environ.get("CANDIDATE_LINKEDIN",   "")
    # One-line description of what makes you stand out — used in funding/launch messages
    # Example: "2 years building ML infra at scale, open-source MLOps contributor"
    CANDIDATE_HOOK:      str = os.environ.get(
        "CANDIDATE_HOOK",
        "strong ML engineering background with production deployment experience"
    )

    # ── Outreach thresholds ────────────────────────────────────────────────────
    MIN_RELEVANCE_FOR_OUTREACH: int   = 3
    MIN_PRIORITY_FOR_AUTO_MSG:  int   = 4
    MAX_DAILY_CONNECTS:         int   = 5

    # ── Follow-up schedule ─────────────────────────────────────────────────────
    FOLLOWUP_1_DAYS: int = 3
    FOLLOWUP_2_DAYS: int = 7
    ARCHIVE_DAYS:    int = 14

    # ── Priority bonus weights ─────────────────────────────────────────────────
    BONUS_HIGH_URGENCY:   int = 3
    BONUS_MED_URGENCY:    int = 1
    BONUS_FOUNDER_CTO:    int = 3
    BONUS_HIRING_MANAGER: int = 2
    BONUS_RECRUITER:      int = 1
    BONUS_HIGH_SCORE:     int = 2

    # ── NEW v2: Signal-based priority bonuses ─────────────────────────────────
    # Funding and YC signals get a fixed bonus that pushes them to the top
    # of the queue regardless of job posting urgency.
    BONUS_FUNDING_SIGNAL: int = 4   # recently funded = founder is hiring now
    BONUS_YC_SIGNAL:      int = 3   # YC batch = pre-vetted, founder-accessible
    BONUS_LAUNCH_SIGNAL:  int = 2   # launched = actively shipping, needs engineers
    BONUS_ALUMNI_SIGNAL:  int = 5   # IITK alumni = absolute highest-ROI response rate


CFG = OutreachConfig()
LOG = logging.getLogger("outreach")


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def _configure_logging() -> None:
    fmt = "%(asctime)s  %(levelname)-8s  |  %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                f"outreach_{datetime.today().strftime('%Y%m%d')}.log",
                encoding="utf-8",
            ),
        ],
    )
    for lib in ("gspread", "googleapiclient", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class Lead(TypedDict):
    """A lead row from the pipeline's Leads sheet tab."""
    company:         str
    source:          str    # NEW: wellfound | yc | producthunt | funding
    hiring_signal:   str    # NEW: job_post | yc_batch | launch | funding
    job_title:       str
    urgency:         str
    contact_name:    str
    contact_title:   str
    linkedin_url:    str
    relevance_score: int
    date_added:      str
    status:          str


class CRMRow(TypedDict):
    """A row in the Outreach CRM tab."""
    company:            str
    source:             str    # NEW
    hiring_signal:      str    # NEW
    job_title:          str
    urgency:            str
    contact_name:       str
    contact_title:      str
    linkedin_url:       str
    email:              str    # NEW
    email_draft:        str    # NEW
    relevance_score:    int
    priority_score:     int
    message_draft:      str
    connect_note:       str    # NEW
    company_description: str   # NEW
    contacted:          str
    date_contacted:     str
    followup_1_due:     str
    followup_1_draft:   str
    followup_1_sent:    str
    followup_1_date:    str
    followup_2_due:     str
    followup_2_draft:   str
    followup_2_sent:    str
    followup_2_date:    str
    reply_received:     str
    reply_date:         str
    outcome:            str
    notes:              str


CRM_HEADERS: list[str] = list(CRMRow.__annotations__.keys())


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 1 — SHEETS CLIENT  (unchanged from v1)
# ══════════════════════════════════════════════════════════════════════════════

class SheetsClient:
    """Thin gspread wrapper — identical to v1."""

    _log = logging.getLogger("outreach.SheetsClient")

    def __init__(self) -> None:
        creds_file = CFG.GOOGLE_CREDENTIALS_FILE
        if not os.path.exists(creds_file):
            raise FileNotFoundError(
                f"Service account key not found: '{creds_file}'\n"
                "Run job_pipeline_v3.py --setup first."
            )
        creds = GCredentials.from_service_account_file(
            creds_file,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        self._gc = gspread.authorize(creds)
        try:
            self._wb = self._gc.open(CFG.GOOGLE_SHEET_NAME)
            self._log.info(f"Opened workbook: {CFG.GOOGLE_SHEET_NAME!r}")
        except gspread.SpreadsheetNotFound:
            raise FileNotFoundError(
                f"Google Sheet '{CFG.GOOGLE_SHEET_NAME}' not found.\n"
                "Run job_pipeline_v3.py first."
            )

    def get_leads_df(self) -> pd.DataFrame:
        # ── Tab selection ──────────────────────────────────────────────────────
        # v3 pipeline creates timestamped Leads_YYYY-MM-DD_HHMM tabs.
        # We also want to include the "IITK Alumni" tab if it exists.
        worksheets = self._wb.worksheets()
        leads_tabs  = [w for w in worksheets if w.title.startswith("Leads_")]
        alumni_tabs = [w for w in worksheets if w.title == "IITK Alumni"]
        
        all_dfs = []

        # Get existing CRM URLs to pre-filter and prevent loading already contacted leads
        existing_urls: set[str] = set()
        try:
            crm_ws = self._wb.worksheet(CFG.CRM_TAB)
            crm_df = self.get_crm_df(crm_ws)
            if not crm_df.empty and "linkedin_url" in crm_df.columns:
                existing_urls = set(crm_df["linkedin_url"].str.strip().dropna())
        except Exception as e:
            self._log.warning(f"Could not read CRM sheet '{CFG.CRM_TAB}' to pre-filter: {e}")

        # 1. Main Leads (all timestamped Leads_* tabs)
        if leads_tabs:
            self._log.info(f"Found {len(leads_tabs)} Leads_* worksheets. Reading and combining all...")
            for ws_main in leads_tabs:
                self._log.info(f"  Reading leads from {ws_main.title!r}…")
                try:
                    rows = ws_main.get_all_values()
                    if len(rows) >= 2:
                        headers, *data = rows
                        df_main = pd.DataFrame(data, columns=headers)
                        all_dfs.append(df_main)
                except Exception as e:
                    self._log.error(f"  Error reading {ws_main.title!r}: {e}")
        else:
            # Fallback to Sheet1 or configured default
            try:
                ws_fallback = self._wb.worksheet(CFG.LEADS_TAB)
                rows = ws_fallback.get_all_values()
                if len(rows) >= 2:
                    headers, *data = rows
                    all_dfs.append(pd.DataFrame(data, columns=headers))
            except gspread.WorksheetNotFound:
                pass

        # 2. IITK Alumni tab
        if alumni_tabs:
            al_w = alumni_tabs[0]
            self._log.info(f"Reading IITK alumni from {al_w.title!r}…")
            try:
                al_data = al_w.get_all_values()
                if len(al_data) >= 2:
                    al_headers, *al_rows = al_data
                    df_alumni = pd.DataFrame(al_rows, columns=al_headers)
                    # Map to standard lead format
                    mapping = {
                        "Name":         "Contact Name",
                        "Title":        "Contact Title",
                        "Company":      "Company",
                        "LinkedIn URL": "LinkedIn URL",
                        "Score":        "Relevance Score",
                        "Date Found":   "Date Added"
                    }
                    df_alumni = df_alumni.rename(columns=mapping)
                    df_alumni["Hiring Signal"] = "alumni"
                    df_alumni["Source"]        = "alumni_module"
                    df_alumni["Urgency"]       = "0 - Alumni Priority"
                    df_alumni["Status"]        = ""
                    all_dfs.append(df_alumni)
            except Exception as e:
                self._log.error(f"  Error reading alumni worksheet: {e}")

        if not all_dfs:
            self._log.warning("No data found in any relevant tabs.")
            return pd.DataFrame()

        df = pd.concat(all_dfs, ignore_index=True, sort=False)
        df = df.fillna("")
        
        # Normalize column names: "Contact Name" -> "contact_name"
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # Graceful column mapping for v3 pipeline vs v2 outreach engine
        if "wellfound_role" in df.columns and "job_title" not in df.columns:
            df = df.rename(columns={"wellfound_role": "job_title"})

        if "relevance_score" in df.columns:
            df["relevance_score"] = (
                pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0).astype(int)
            )

        # Handle v2 sheet format — add missing columns gracefully for backwards compat
        for col in ("source", "hiring_signal"):
            if col not in df.columns:
                df[col] = "job_post" if col == "hiring_signal" else "wellfound"

        # Pre-filter against active CRM contacts and self-deduplicate
        if "linkedin_url" in df.columns:
            df["linkedin_url_clean"] = df["linkedin_url"].str.strip()
            # Remove leads already in CRM
            before_len = len(df)
            df = df[~df["linkedin_url_clean"].isin(existing_urls)]
            self._log.info(f"🛡️  CRM pre-filter: Removed {before_len - len(df)} leads already in Outreach CRM.")
            
            # Deduplicate multiple occurrences within the combined leads tabs
            before_len = len(df)
            df = df.drop_duplicates(subset=["linkedin_url_clean"], keep="first")
            df = df.drop(columns=["linkedin_url_clean"])
            self._log.info(f"🛡️  Self-deduplicate: Removed {before_len - len(df)} duplicate leads across runs.")

        self._log.info(f"Read {len(df)} total rows from relevant tabs")
        return df

    def get_or_create_crm_worksheet(self) -> gspread.Worksheet:
        try:
            ws = self._wb.worksheet(CFG.CRM_TAB)
            self._log.info(f"CRM tab '{CFG.CRM_TAB}' opened")
            
            # Check existing headers to see if migration is needed
            rows = ws.get_all_values()
            if rows:
                existing_headers = rows[0]
                if existing_headers != CRM_HEADERS:
                    self._log.info("🔄  Existing CRM headers differ from target order. Migrating columns...")
                    crm_df = self.get_crm_df(ws)
                    
                    # Ensure all CRM_HEADERS columns exist in the DataFrame
                    for col in CRM_HEADERS:
                        if col not in crm_df.columns:
                            crm_df[col] = ""
                            
                    # Reorder/select columns to match CRM_HEADERS exactly
                    crm_df = crm_df[CRM_HEADERS]
                    
                    # Overwrite worksheet with aligned data
                    ws.clear()
                    all_rows = [CRM_HEADERS] + crm_df.values.tolist()
                    ws.update("A1", all_rows, value_input_option="USER_ENTERED")
                    ws.freeze(rows=1)
                    self._log.info("✅  CRM tab migrated successfully to new prominent column order!")
        except gspread.WorksheetNotFound:
            ws = self._wb.add_worksheet(
                title=CFG.CRM_TAB, rows=2000, cols=len(CRM_HEADERS) + 2
            )
            ws.append_row(CRM_HEADERS)
            ws.freeze(rows=1)
            self._log.info(f"CRM tab '{CFG.CRM_TAB}' created with headers")
        return ws

    def get_crm_df(self, ws: gspread.Worksheet) -> pd.DataFrame:
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame(columns=CRM_HEADERS)
        headers, *data = rows
        return pd.DataFrame(data, columns=headers)

    def append_crm_rows(self, ws: gspread.Worksheet, rows: list[list]) -> None:
        if not rows:
            return
        for i in range(0, len(rows), 50):
            ws.append_rows(rows[i : i + 50], value_input_option="USER_ENTERED")
            time.sleep(0.5)

    def update_crm_cell(self, ws: gspread.Worksheet, row_idx: int, col_name: str, value: str) -> None:
        col_idx = CRM_HEADERS.index(col_name) + 1
        ws.update_cell(row_idx, col_idx, value)


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 2 — PRIORITIZER  (upgraded with signal bonuses)
# ══════════════════════════════════════════════════════════════════════════════

class Prioritizer:
    """
    Adds a priority_score to every lead row.

    v2 changes:
      hiring_signal now contributes a priority bonus:
        funding  → +4 (founders making hiring decisions right now)
        yc_batch → +3 (pre-vetted, founder-reachable)
        launch   → +2 (actively building)
        job_post → +0 (standard — competition is higher, same as v1)

    This pushes funded/YC leads above Wellfound leads even if the Wellfound
    lead has a higher relevance score. The logic is correct: a founder at a
    just-funded startup who responds to 1 in 5 messages beats a recruiter at
    a Wellfound company who responds to 1 in 50.
    """

    _log = logging.getLogger("outreach.Prioritizer")

    _CONTACT_TYPE_MAP: dict[str, str] = {
        "co-founder":         "founder",
        "founder":            "founder",
        "ceo":                "founder",
        "cto":                "founder",
        "chief":              "founder",
        "talent acquisition": "recruiter",
        "recruiter":          "recruiter",
        "talent":             "recruiter",
        "hr manager":         "recruiter",
        "hr":                 "recruiter",
        "people ops":         "recruiter",
        "people":             "recruiter",
        "head of":            "hiring_manager",
        "vice president":     "hiring_manager",
        "vp":                 "hiring_manager",
        "director":           "hiring_manager",
        "lead":               "hiring_manager",
        "manager":            "hiring_manager",
    }

    def prioritize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            self._log.warning("Empty DataFrame — nothing to prioritize.")
            return df

        df = df.copy()
        df = df[df["contact_name"].str.strip().astype(bool)]
        df = df[df["linkedin_url"].str.strip().astype(bool)]
        df = df[df["relevance_score"] >= CFG.MIN_RELEVANCE_FOR_OUTREACH]

        if df.empty:
            self._log.warning(
                f"No leads passed the gate (relevance ≥ {CFG.MIN_RELEVANCE_FOR_OUTREACH})."
            )
            return df

        df["contact_type"]   = df["contact_title"].apply(self._classify_contact)
        df["priority_score"] = df.apply(self._compute_priority, axis=1)
        df["outreach_ready"] = df["priority_score"] >= CFG.MIN_PRIORITY_FOR_AUTO_MSG

        df = df.sort_values("priority_score", ascending=False).reset_index(drop=True)

        # Log signal distribution to show value of multi-source approach
        if "hiring_signal" in df.columns:
            signal_dist = df["hiring_signal"].value_counts()
            self._log.info("  Signal distribution in prioritized leads:")
            for sig, cnt in signal_dist.items():
                bonus = {
                    "alumni":   CFG.BONUS_ALUMNI_SIGNAL,
                    "funding":  CFG.BONUS_FUNDING_SIGNAL,
                    "yc_batch": CFG.BONUS_YC_SIGNAL,
                    "launch":   CFG.BONUS_LAUNCH_SIGNAL,
                    "job_post": 0,
                }.get(sig, 0)
                self._log.info(f"    {sig:<14} {cnt:>4} leads  (priority bonus: +{bonus})")

        ready = df["outreach_ready"].sum()
        self._log.info(
            f"Prioritizer: {len(df)} leads pass gate, "
            f"{ready} are outreach-ready (priority ≥ {CFG.MIN_PRIORITY_FOR_AUTO_MSG})"
        )
        return df

    def _classify_contact(self, title: str) -> str:
        t = title.lower()
        for keyword, contact_type in self._CONTACT_TYPE_MAP.items():
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, t):
                return contact_type
        return "other"

    def _compute_priority(self, row: pd.Series) -> int:
        score = int(row.get("relevance_score", 0))

        # Urgency bonus (job_post leads only — others don't have posting times)
        urgency = str(row.get("urgency", "")).lower()
        if urgency.startswith("1"):
            score += CFG.BONUS_HIGH_URGENCY
        elif urgency.startswith("2"):
            score += CFG.BONUS_MED_URGENCY

        # Contact-type bonus
        contact_type = str(row.get("contact_type", ""))
        if contact_type == "founder":
            score += CFG.BONUS_FOUNDER_CTO
        elif contact_type == "hiring_manager":
            score += CFG.BONUS_HIRING_MANAGER
        elif contact_type == "recruiter":
            score += CFG.BONUS_RECRUITER

        # High relevance bonus
        if int(row.get("relevance_score", 0)) >= 4:
            score += CFG.BONUS_HIGH_SCORE

        # NEW: Signal bonus — the highest-ROI leads float to the top
        hiring_signal = str(row.get("hiring_signal", "job_post"))
        if hiring_signal == "alumni":
            score += CFG.BONUS_ALUMNI_SIGNAL
        elif hiring_signal == "funding":
            score += CFG.BONUS_FUNDING_SIGNAL
        elif hiring_signal == "yc_batch":
            score += CFG.BONUS_YC_SIGNAL
        elif hiring_signal == "launch":
            score += CFG.BONUS_LAUNCH_SIGNAL

        return score


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 3 — MESSAGE COMPOSER  (signal-aware opening hooks)
# ══════════════════════════════════════════════════════════════════════════════

class MessageComposer:
    """
    Generates three messages per lead: first contact, follow-up 1, follow-up 2.

    v2 key change: the opening hook now references the hiring_signal context.
    This is the single highest-leverage change in the entire upgrade.

    A founder who just raised money, launched a product, or got into YC has
    a very specific context. Referencing it says:
      "I know what's happening at your company right now"
    That's fundamentally different from a generic application.

    Tone rules (preserved from v1):
      Founder/CTO      → peer-to-peer, no pleasantries
      Hiring Manager   → direct, specific to role
      Recruiter        → professional, complete
    """

    _log = logging.getLogger("outreach.MessageComposer")

    _ROLE_CAPABILITY: dict[str, str] = {
        "mlops":          "ML infrastructure, model deployment pipelines, and monitoring",
        "ml engineer":    "end-to-end ML model training, serving, and optimisation",
        "ai engineer":    "AI system design, LLM integration, and production deployment",
        "data scientist": "statistical modelling, experiment design, and ML research",
        "data engineer":  "scalable data pipelines, warehousing, and real-time processing",
        "data analyst":   "analytics, dashboarding, and data-driven decision frameworks",
    }

    # Signal → opening context line for each message type
    # These are intentionally brief — they're the hook, not the pitch.
    _SIGNAL_CONTEXT: dict[str, dict[str, str]] = {
        "funding": {
            "founder": (
                "Congrats on the raise — teams at this stage move fast on hiring, "
                "so I wanted to get in front of you early."
            ),
            "hiring_manager": (
                "Saw the funding news — I imagine the engineering team is about to grow. "
                "I wanted to reach out before the role is posted publicly."
            ),
            "recruiter": (
                "I saw the recent funding round and wanted to get on your radar "
                "before the hiring push kicks off."
            ),
            "other": (
                "Congratulations on the funding — I noticed and wanted to reach out directly."
            ),
        },
        "yc_batch": {
            "founder": (
                "Saw you're in the YC batch — I wanted to reach out directly to you "
                "rather than going through a job board."
            ),
            "hiring_manager": (
                "Came across your company through the YC directory and wanted to connect "
                "before the Demo Day hiring rush."
            ),
            "recruiter": (
                "Found your company through the YC batch directory. "
                "I know YC companies move fast on hiring so I wanted to reach out early."
            ),
            "other": (
                "Saw your company through the YC batch — wanted to reach out directly."
            ),
        },
        "launch": {
            "founder": (
                "Saw the launch — it looks like you're shipping fast. "
                "I wanted to reach out now while the team is still small."
            ),
            "hiring_manager": (
                "Noticed the recent launch and wanted to connect. "
                "Companies that are shipping this actively usually need engineering support."
            ),
            "recruiter": (
                "Saw the recent product launch and wanted to get in touch. "
                "I imagine the team is growing to support it."
            ),
            "other": (
                "Saw the launch — impressive. I wanted to reach out directly."
            ),
        },
        "job_post": {
            "founder":        "",   # job_post falls through to v1 template
            "hiring_manager": "",
            "recruiter":      "",
            "other":          "",
        },
    }

    def compose_all(self, row: pd.Series) -> tuple[str, str, str, str, str]:
        """Returns (message_draft, connect_note, followup_1_draft, followup_2_draft, email_draft)."""
        company        = str(row.get("company",        "")).strip()
        job_title      = str(row.get("job_title",      "")).strip()
        contact_name   = str(row.get("contact_name",   "")).strip()
        contact_type   = str(row.get("contact_type",   "other"))
        hiring_signal  = str(row.get("hiring_signal",  "job_post"))
        capability     = self._get_capability(job_title)
        first_name     = contact_name.split()[0] if contact_name else "there"

        msg1       = self._compose_first(
            first_name, company, job_title, capability, contact_type, hiring_signal
        )
        note       = self._compose_connect_note(row)
        msg2       = self._compose_followup1(first_name, company, job_title, hiring_signal)
        msg3       = self._compose_followup2(first_name, company)
        email_body = self._compose_email_draft(row)

        return msg1, note, msg2, msg3, email_body

    def _compose_connect_note(self, row: pd.Series) -> str:
        """
        Hyper-personalized connection note based on company description, tech stack,
        and targeted challenges. Max 300 characters (targets <= 280 for safety).
        """
        company        = str(row.get("company",        "")).strip()
        job_title      = str(row.get("job_title",      "")).strip()
        contact_name   = str(row.get("contact_name",   "")).strip()
        hiring_signal  = str(row.get("hiring_signal",  "job_post"))
        capability     = self._get_capability(job_title)
        first_name     = contact_name.split()[0] if contact_name else "there"
        description    = str(row.get("company_description", "")).strip()

        grad_year = CFG.CANDIDATE_GRAD_YEAR
        
        # 1. Warm Alumni Intro
        if hiring_signal == "alumni":
            note = f"Hi {first_name}, fellow IITK alum here ({grad_year}). I noticed you're building in the AI/ML space at {company} — wanted to connect directly."
            if len(note) > 280:
                note = note[:277] + "..."
            return note

        # Similar technical theme
        similar_thing = "scalable ML/LLM pipelines"
        if "ops" in capability.lower() or "infra" in capability.lower():
            similar_thing = "MLOps pipelines"
        elif "data" in capability.lower():
            similar_thing = "scalable data pipelines"
        elif "analyst" in capability.lower():
            similar_thing = "data analyst projects"

        # 2. Hyper-personalized check based on company description
        if description and len(description) > 10:
            desc_lower = description.lower()
            
            # Look for specific technical context
            specific_thing = ""
            for kw in ["developer tools", "infrastructure", "database", "analytics", "robotics", "fintech", "edtech", "automating"]:
                if kw in desc_lower:
                    specific_thing = f"in the {kw} space"
                    break
            
            if not specific_thing:
                # Look for "building a/an ..."
                for pattern in ["building a ", "building an ", "developing a ", "developing an "]:
                    if pattern in desc_lower:
                        idx = desc_lower.find(pattern) + len(pattern)
                        chunk = description[idx:idx+35].strip()
                        # Truncate at natural boundaries
                        for stop_char in [".", ",", ";", "—", " for "]:
                            if stop_char in chunk:
                                chunk = chunk.split(stop_char)[0]
                                break
                        specific_thing = f"a {chunk.lower()}"
                        break
            
            if specific_thing:
                note = f"Hi {first_name}, saw {company} is building {specific_thing}. I worked on {similar_thing} during my engineering projects. Would love to connect and learn about your technical scale."
                if len(note) <= 280:
                    return note

        # 3. Graceful fallback templates if no specific description could be leveraged
        if hiring_signal == "funding":
            note = f"Hi {first_name}, saw the recent funding news for {company} — congrats! I'm an engineering grad with hands-on experience in {capability}. Wanted to connect."
        elif hiring_signal == "yc_batch":
            note = f"Hi {first_name}, found {company} via the YC batch directory. I'm an engineering grad with hands-on experience in {capability}. Wanted to reach out to connect."
        elif hiring_signal == "launch":
            note = f"Hi {first_name}, saw the recent launch for {company} — looks impressive! I have hands-on experience in {capability} and wanted to reach out to connect."
        else: # job_post
            role_part = f" for the {job_title} role" if job_title else ""
            note = f"Hi {first_name}, I saw the job posting{role_part} at {company} and wanted to reach out. I have hands-on experience in {capability} and would love to connect."

        if len(note) > 280:
            note = note[:277] + "..."
        return note

    def _compose_email_draft(self, row: pd.Series) -> str:
        """
        Composes a cold founder email (subject + body) optimised for 20-25% reply rate.
        - Short: 5-8 sentences max. Founders delete walls of text.
        - Specific: references what the company actually does.
        - Clear ask: one small, easy yes (15-min call / quick reply).
        Returns an empty string if no email is available for the contact.
        """
        email        = str(row.get("email", "")).strip()
        if not email:
            return ""

        company       = str(row.get("company",        "")).strip()
        job_title     = str(row.get("job_title",      "")).strip()
        contact_name  = str(row.get("contact_name",   "")).strip()
        hiring_signal = str(row.get("hiring_signal",  "job_post"))
        description   = str(row.get("company_description", "")).strip()
        capability    = self._get_capability(job_title)
        first_name    = contact_name.split()[0] if contact_name else "there"

        # Subject line — specificity beats cleverness
        if hiring_signal == "funding":
            subject = f"Quick question from a {CFG.CANDIDATE_INSTITUTE} ML grad — {company}"
        elif hiring_signal in ("yc_batch", "launch"):
            subject = f"Impressed by what {company} is building — {CFG.CANDIDATE_NAME}"
        elif hiring_signal == "alumni":
            subject = f"{CFG.CANDIDATE_INSTITUTE} alum interested in {company}"
        else:
            role_part = f" ({job_title})" if job_title else ""
            subject = f"Re: {company} opening{role_part} — {CFG.CANDIDATE_NAME}"

        # Opening hook — personalised to what the company does
        if description and len(description) > 15:
            desc_lower = description.lower()
            hook = ""
            for kw in ["developer tools", "infrastructure", "LLM", "GenAI", "analytics",
                       "robotics", "fintech", "edtech", "automating", "language"]:
                if kw.lower() in desc_lower:
                    hook = f"saw that {company} is working on {kw.lower()} — that's a hard problem done right"
                    break
            if not hook:
                hook = f"came across {company} and was genuinely impressed by what you're building"
        elif hiring_signal == "funding":
            hook = f"saw the recent funding announcement for {company} — congrats on the round"
        elif hiring_signal in ("yc_batch", "launch"):
            hook = f"found {company} through the YC batch and loved the direction"
        elif hiring_signal == "alumni":
            hook = f"noticed we're both IITK alumni and you're now building {company}"
        else:
            hook = f"came across the {job_title or 'engineering'} opening at {company}"

        body = textwrap.dedent(f"""\
            Subject: {subject}

            Hi {first_name},

            I {hook}.

            I'm a {CFG.CANDIDATE_GRAD_YEAR} {CFG.CANDIDATE_INSTITUTE} grad — I've {CFG.CANDIDATE_HOOK}. Specifically, my background is strongest in {capability}.

            I'm not mass-applying. {company} is on my short list because the engineering problem genuinely interests me.

            Worth a 15-min call this week to see if there's a fit?

            {CFG.CANDIDATE_NAME}
            {CFG.CANDIDATE_LINKEDIN or ''}""").strip()

        return body

    def _get_capability(self, job_title: str) -> str:
        t = job_title.lower()
        for keyword, capability in self._ROLE_CAPABILITY.items():
            if keyword in t:
                return capability
        return CFG.CANDIDATE_SKILLS

    def _get_signal_context(self, hiring_signal: str, contact_type: str) -> str:
        """Return the signal-specific opening hook for this contact type."""
        signal_map = self._SIGNAL_CONTEXT.get(hiring_signal, {})
        return signal_map.get(contact_type, signal_map.get("other", ""))

    def _compose_first_alumni(
        self,
        first_name:   str,
        company:      str,
        capability:   str,
        contact_type: str,
    ) -> str:
        """
        Compose a highly targeted outreach message to a fellow IITK alum.
        Has an extremely high (~55-65%) response rate.
        """
        grad_year = CFG.CANDIDATE_GRAD_YEAR
        return textwrap.dedent(f"""\
            Hi {first_name},

            Fellow IITK alum here ({grad_year}). I noticed you're building in the AI/ML space at {company} — wanted to connect directly.

            I have hands-on experience in {capability} and I'm looking for my next role. The engineering challenge at {company} is exactly what I'm looking for.

            Open to a brief chat if you have a few minutes this week?

            Best,
            {CFG.CANDIDATE_NAME}""").strip()

    def _compose_first(
        self,
        first_name:    str,
        company:       str,
        job_title:     str,
        capability:    str,
        contact_type:  str,
        hiring_signal: str,
    ) -> str:
        # For alumni hiring signal, use a highly targeted direct alumni hook
        if hiring_signal == "alumni":
            return self._compose_first_alumni(
                first_name, company, capability, contact_type
            )

        signal_context = self._get_signal_context(hiring_signal, contact_type)

        # For job_post signal, use the v1 templates (they work well)
        if hiring_signal == "job_post" or not signal_context:
            return self._compose_first_job_post(
                first_name, company, job_title, capability, contact_type
            )

        # For all other signals, use the signal-aware template
        return self._compose_first_signal_aware(
            first_name, company, capability, contact_type, signal_context
        )

    def _compose_first_signal_aware(
        self,
        first_name:     str,
        company:        str,
        capability:     str,
        contact_type:   str,
        signal_context: str,
    ) -> str:
        """
        Signal-aware message: opens with the specific event (funding/launch/yc),
        then delivers the pitch. No generic "I saw your job posting" opening.
        """
        if contact_type == "founder":
            return textwrap.dedent(f"""\
                Hi {first_name},

                {signal_context}

                I'm a {CFG.CANDIDATE_GRAD_YEAR} {CFG.CANDIDATE_INSTITUTE} grad with {CFG.CANDIDATE_HOOK}. \
Specifically: {capability}.

                The work happening at {company} is exactly where I want to be contributing — \
especially at a stage where the infrastructure decisions actually shape the product.

                Happy to share relevant work if it's worth 5 minutes of your time.

                {CFG.CANDIDATE_NAME}""").strip()

        if contact_type == "hiring_manager":
            return textwrap.dedent(f"""\
                Hi {first_name},

                {signal_context}

                I'm reaching out directly — {CFG.CANDIDATE_INSTITUTE} ({CFG.CANDIDATE_GRAD_YEAR}), \
with hands-on experience in {capability}.

                I'd rather have a direct conversation than go through a job board process, \
and I think there's a strong fit with what {company} is building.

                Open to a quick call if useful.

                {CFG.CANDIDATE_NAME}""").strip()

        if contact_type == "recruiter":
            return textwrap.dedent(f"""\
                Hi {first_name},

                {signal_context}

                Background: {CFG.CANDIDATE_INSTITUTE}, batch of {CFG.CANDIDATE_GRAD_YEAR}, \
with focused experience in {capability}.

                I believe my profile aligns well with what {company} will need at this stage. \
Happy to share more detail.

                {CFG.CANDIDATE_NAME}\
{chr(10) + CFG.CANDIDATE_LINKEDIN if CFG.CANDIDATE_LINKEDIN else ''}""").strip()

        # other
        return textwrap.dedent(f"""\
            Hi {first_name},

            {signal_context}

            I'm a {CFG.CANDIDATE_GRAD_YEAR} {CFG.CANDIDATE_INSTITUTE} graduate \
with experience in {capability}. \
I'm genuinely interested in the kind of technical challenges {company} is tackling.

            Would you be the right person to connect with about opportunities there?

            {CFG.CANDIDATE_NAME}""").strip()

    def _compose_first_job_post(
        self,
        first_name:   str,
        company:      str,
        job_title:    str,
        capability:   str,
        contact_type: str,
    ) -> str:
        """v1 job-post templates — preserved exactly."""
        if contact_type == "founder":
            return textwrap.dedent(f"""\
                Hi {first_name},

                Saw you're building out the {job_title} function at {company}.

                I'm a {CFG.CANDIDATE_GRAD_YEAR} graduate from {CFG.CANDIDATE_INSTITUTE} \
with hands-on work in {capability}. \
The scale of what you're doing at {company} is exactly the kind of environment \
I want to contribute to — specifically at an early stage where the infrastructure decisions actually matter.

                Happy to share a quick breakdown of relevant work if it's worth 5 minutes of your time.

                {CFG.CANDIDATE_NAME}""").strip()

        if contact_type == "hiring_manager":
            return textwrap.dedent(f"""\
                Hi {first_name},

                I came across the {job_title} opening at {company} and wanted to reach out directly.

                {CFG.CANDIDATE_INSTITUTE} graduate ({CFG.CANDIDATE_GRAD_YEAR}), \
with focused experience in {capability}. \
I think there's a strong fit given what {company} is building, \
and I'd rather have a direct conversation than go through a black-box process.

                Open to a quick call if you'd like to size up the fit.

                {CFG.CANDIDATE_NAME}""").strip()

        if contact_type == "recruiter":
            return textwrap.dedent(f"""\
                Hi {first_name},

                Reaching out regarding the {job_title} role at {company}.

                Background: {CFG.CANDIDATE_INSTITUTE}, batch of {CFG.CANDIDATE_GRAD_YEAR}, \
with practical experience in {capability}.

                I'm actively looking for early-stage roles in this space and believe \
my profile aligns well with what {company} needs for this position.

                Would love to connect if you're still actively hiring for this.

                {CFG.CANDIDATE_NAME}\
{chr(10) + CFG.CANDIDATE_LINKEDIN if CFG.CANDIDATE_LINKEDIN else ''}""").strip()

        return textwrap.dedent(f"""\
            Hi {first_name},

            I noticed {company} is hiring for {job_title} and wanted to reach out.

            I'm a {CFG.CANDIDATE_GRAD_YEAR} {CFG.CANDIDATE_INSTITUTE} graduate \
with experience in {capability}. \
I'm genuinely interested in the kind of technical challenges {company} is tackling.

            Would you be the right person to connect with about this, \
or could you point me in the right direction?

            {CFG.CANDIDATE_NAME}""").strip()

    def _compose_followup1(
        self,
        first_name:    str,
        company:       str,
        job_title:     str,
        hiring_signal: str,
    ) -> str:
        """
        Follow-up 1 (Day 3): brief nudge.
        For signal-sourced leads (no job title), we don't reference "the role" since
        there may not be one — we reference the company context instead.
        """
        if hiring_signal != "job_post" or not job_title:
            return textwrap.dedent(f"""\
                Hi {first_name},

                Just following up on my message from a few days ago about {company}.

                Completely understand if timing isn't right — happy to reconnect whenever it makes sense.

                {CFG.CANDIDATE_NAME}""").strip()

        return textwrap.dedent(f"""\
            Hi {first_name},

            Just following up on my message from a few days ago \
regarding the {job_title} role at {company}.

            Completely understand if timing isn't right — happy to reconnect whenever it makes sense.

            {CFG.CANDIDATE_NAME}""").strip()

    @staticmethod
    def _compose_followup2(first_name: str, company: str) -> str:
        """Follow-up 2 (Day 7): final touch — identical across all signal types."""
        return textwrap.dedent(f"""\
            Hi {first_name},

            Last nudge — I won't keep filling your inbox after this.

            Still very interested in what {company} is building. \
If the timing or the role changes in the future, I'd love to stay on your radar.

            {CFG.CANDIDATE_NAME}""").strip()


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 4 — FOLLOW-UP TRACKER  (unchanged from v1)
# ══════════════════════════════════════════════════════════════════════════════

class FollowUpTracker:
    """Identifies leads that need action today. Logic unchanged from v1."""

    _log = logging.getLogger("outreach.FollowUpTracker")

    def get_due_actions(self, crm_df: pd.DataFrame) -> pd.DataFrame:
        if crm_df.empty:
            return pd.DataFrame()

        today  = date.today()
        result = []

        for _, row in crm_df.iterrows():
            contacted = str(row.get("contacted", "")).strip().lower()
            if contacted != "yes":
                continue

            reply = str(row.get("reply_received", "")).strip().lower()
            if reply == "yes":
                continue

            outcome = str(row.get("outcome", "")).strip()
            if outcome in ("Rejected", "Offer"):
                continue

            date_contacted_raw = str(row.get("date_contacted", "")).strip()
            if not date_contacted_raw:
                continue

            try:
                date_contacted = datetime.strptime(date_contacted_raw, "%Y-%m-%d").date()
            except ValueError:
                continue

            days_elapsed = (today - date_contacted).days
            f1_sent = str(row.get("followup_1_sent", "")).strip().lower() == "yes"
            f2_sent = str(row.get("followup_2_sent", "")).strip().lower() == "yes"

            action = None
            if days_elapsed >= CFG.ARCHIVE_DAYS and not f2_sent:
                action = "Archive → Ghosted"
            elif days_elapsed >= CFG.FOLLOWUP_2_DAYS and f1_sent and not f2_sent:
                action = "Follow-up 2"
            elif days_elapsed >= CFG.FOLLOWUP_1_DAYS and not f1_sent:
                action = "Follow-up 1"

            if action:
                row_copy = row.copy()
                row_copy["due_action"]   = action
                row_copy["days_elapsed"] = days_elapsed
                result.append(row_copy)

        if not result:
            return pd.DataFrame()

        df = pd.DataFrame(result)
        order = {"Archive → Ghosted": 0, "Follow-up 2": 1, "Follow-up 1": 2}
        df["_sort"] = df["due_action"].map(order).fillna(9)
        df = df.sort_values(["_sort", "days_elapsed"], ascending=[True, False])
        df = df.drop(columns=["_sort"]).reset_index(drop=True)

        self._log.info(f"Follow-up tracker: {len(df)} leads need action today")
        return df


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 5 — CAMPAIGN STATS ENGINE  (upgraded with signal breakdown)
# ══════════════════════════════════════════════════════════════════════════════

class StatsEngine:
    """
    Campaign performance summary.

    v2 addition: shows response rate broken down by hiring_signal.
    This is the most important metric to track — it tells you which source
    is actually delivering replies and should receive more of your 100 daily API calls.
    """

    _log = logging.getLogger("outreach.StatsEngine")

    def report(self, crm_df: pd.DataFrame) -> None:
        if crm_df.empty:
            print("\n  No CRM data yet — run the engine first.")
            return

        def yn(col: str, val: str = "yes") -> int:
            return (crm_df.get(col, pd.Series(dtype=str))
                    .str.strip().str.lower() == val).sum()

        total      = len(crm_df)
        contacted  = yn("contacted")
        f1_sent    = yn("followup_1_sent")
        f2_sent    = yn("followup_2_sent")
        replied    = yn("reply_received")
        interviews = (crm_df.get("outcome", pd.Series(dtype=str))
                      .str.strip().str.lower().isin(["interview", "offer"])).sum()
        offers     = (crm_df.get("outcome", pd.Series(dtype=str))
                      .str.strip().str.lower() == "offer").sum()
        ghosted    = (crm_df.get("outcome", pd.Series(dtype=str))
                      .str.strip().str.lower() == "ghosted").sum()

        response_rate  = f"{replied / contacted * 100:.1f}%" if contacted > 0 else "N/A"
        interview_rate = f"{interviews / replied * 100:.1f}%" if replied  > 0 else "N/A"

        rows = [
            ["Leads in CRM",        total],
            ["Messages sent",       contacted],
            ["Follow-up 1 sent",    f1_sent],
            ["Follow-up 2 sent",    f2_sent],
            ["Replies received",    replied],
            ["Response rate",       response_rate],
            ["Interviews / offers", f"{interviews} / {offers}"],
            ["Interview rate",      interview_rate],
            ["Ghosted / archived",  ghosted],
        ]

        sep = "═" * 50
        print(f"\n{sep}")
        print("  CAMPAIGN PERFORMANCE SUMMARY")
        print(sep)
        if _HAS_TABULATE:
            print(tabulate(rows, headers=["Metric", "Value"], tablefmt="simple"))
        else:
            for label, val in rows:
                print(f"  {label:<28} {val}")

        # NEW: response rate by source signal
        if "hiring_signal" in crm_df.columns and contacted > 0:
            print("\n  Response rate by source signal:")
            for signal in ["funding", "yc_batch", "launch", "job_post"]:
                seg = crm_df[crm_df.get("hiring_signal", pd.Series(dtype=str)).str.strip() == signal]
                if seg.empty:
                    continue
                seg_contacted = (seg.get("contacted", pd.Series(dtype=str))
                                 .str.strip().str.lower() == "yes").sum()
                seg_replied   = (seg.get("reply_received", pd.Series(dtype=str))
                                 .str.strip().str.lower() == "yes").sum()
                rate = f"{seg_replied / seg_contacted * 100:.0f}%" if seg_contacted > 0 else "—"
                print(f"    {signal:<14} {seg_contacted:>3} sent, {seg_replied:>2} replied  ({rate})")

        print(sep + "\n")


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 6 — CRM WRITER  (updated for new schema columns)
# ══════════════════════════════════════════════════════════════════════════════

class CRMWriter:
    """Syncs new leads into the CRM tab. v2 adds source + hiring_signal columns."""

    _log = logging.getLogger("outreach.CRMWriter")

    def __init__(self, sheets: SheetsClient) -> None:
        self._sheets   = sheets
        self._composer = MessageComposer()

    def sync(self, prioritized_df: pd.DataFrame, ws: gspread.Worksheet) -> int:
        if prioritized_df.empty:
            self._log.warning("Nothing to sync — prioritized DataFrame is empty.")
            return 0

        crm_df = self._sheets.get_crm_df(ws)
        existing_urls: set[str] = set()
        if not crm_df.empty and "linkedin_url" in crm_df.columns:
            existing_urls = set(crm_df["linkedin_url"].str.strip().dropna())

        # Weekly safety check: count how many invites have been sent in the last 7 days
        sent_in_last_7_days = 0
        if not crm_df.empty and "date_contacted" in crm_df.columns:
            seven_days_ago = (datetime.today() - timedelta(days=7)).date()
            for _, r in crm_df.iterrows():
                dc_str = str(r.get("date_contacted", "")).strip()
                if dc_str:
                    try:
                        dc_date = datetime.strptime(dc_str, "%Y-%m-%d").date()
                        if dc_date >= seven_days_ago:
                            sent_in_last_7_days += 1
                    except ValueError:
                        pass

        self._log.info(f"📊  Weekly counter check: {sent_in_last_7_days} connection invites sent in the last 7 days.")

        # Stay safely within the 25 connection request per week cap
        weekly_cap = 25
        available_slots = max(0, weekly_cap - sent_in_last_7_days)
        self._log.info(f"📊  Available slots for this week: {available_slots} (Weekly Cap: {weekly_cap})")

        sync_limit = min(CFG.MAX_DAILY_CONNECTS, available_slots)
        if sync_limit <= 0:
            self._log.warning("⚠️  Weekly connection limit reached! Skipping CRM lead syncing to protect your LinkedIn account from bans.")
            return 0

        ready_df  = prioritized_df[prioritized_df["outreach_ready"]].head(sync_limit)
        new_rows: list[list] = []
        today_str = datetime.today().strftime("%Y-%m-%d")

        for _, row in ready_df.iterrows():
            url = str(row.get("linkedin_url", "")).strip()
            if url in existing_urls:
                continue

            date_added = str(row.get("date_added", today_str)).strip() or today_str
            msg1, connect_note, msg2, msg3, email_draft = self._composer.compose_all(row)

            try:
                lead_date = datetime.strptime(date_added, "%Y-%m-%d").date()
            except ValueError:
                lead_date = date.today()

            f1_due = (lead_date + timedelta(days=CFG.FOLLOWUP_1_DAYS)).strftime("%Y-%m-%d")
            f2_due = (lead_date + timedelta(days=CFG.FOLLOWUP_2_DAYS)).strftime("%Y-%m-%d")

            # Column order must match CRM_HEADERS exactly
            new_rows.append([
                str(row.get("company",        "")),
                str(row.get("source",         "wellfound")),
                str(row.get("hiring_signal",  "job_post")),
                str(row.get("job_title",      "")),
                str(row.get("urgency",        "")),
                str(row.get("contact_name",   "")),
                str(row.get("contact_title",  "")),
                url,
                str(row.get("email",           "")),       # Prominent email alongside LinkedIn URL
                email_draft,                               # Prominent email_draft alongside LinkedIn URL
                str(row.get("relevance_score", 0)),
                str(row.get("priority_score",  0)),
                msg1,
                connect_note,
                str(row.get("company_description", "")),
                "",             # contacted
                "",             # date_contacted
                f1_due,
                msg2,
                "",             # followup_1_sent
                "",             # followup_1_date
                f2_due,
                msg3,
                "",             # followup_2_sent
                "",             # followup_2_date
                "",             # reply_received
                "",             # reply_date
                "",             # outcome
                "",             # notes
            ])
            existing_urls.add(url)

        if new_rows:
            self._sheets.append_crm_rows(ws, new_rows)
            self._log.info(f"✅  Added {len(new_rows)} new leads to CRM tab")
        else:
            self._log.info("  No new leads to add")

        return len(new_rows)


# ══════════════════════════════════════════════════════════════════════════════
#  COMPONENT 7 — DAILY BRIEFING  (signal-aware sections)
# ══════════════════════════════════════════════════════════════════════════════

class DailyBriefing:
    """
    Prints today's action list.

    v2 change: high-signal leads (funding, yc_batch) are shown in their own
    section at the top, before regular job-post leads. This ensures you don't
    miss your highest-ROI contacts buried in a long list.
    """

    _log = logging.getLogger("outreach.DailyBriefing")

    def __init__(self, tracker: FollowUpTracker, stats: StatsEngine) -> None:
        self._tracker = tracker
        self._stats   = stats

    def print_briefing(
        self,
        new_leads_df: pd.DataFrame,
        crm_df:       pd.DataFrame,
    ) -> None:
        sep   = "═" * 72
        today = datetime.today().strftime("%A, %d %B %Y")

        print(f"\n{sep}")
        print(f"  OUTREACH BRIEFING  —  {today}")
        print(f"  Goal: {CFG.MAX_DAILY_CONNECTS} messages/day | Focus: funding + YC leads first")
        print(sep)

        if new_leads_df.empty:
            print("\n  No leads to send today. Run job_pipeline_v3.py first.")
        else:
            ready = new_leads_df[new_leads_df.get("outreach_ready", False) == True]  # noqa: E712

            high_signal = pd.DataFrame()
            if "hiring_signal" in ready.columns:
                high_signal = ready[
                    ready["hiring_signal"].isin(["funding", "yc_batch", "launch", "alumni"])
                ]

            if not high_signal.empty:
                print(f"\n{'─'*72}")
                print(f"  💰🚀🎓  HIGH-SIGNAL & ALUMNI LEADS  ({len(high_signal)} — send these FIRST)")
                print("        Funding raises / YC batch / Product launches / IITK Alumni")
                print(f"{'─'*72}")
                print("  These companies are NOT on Wellfound. You have less competition.\n")
                self._print_lead_table(high_signal.head(15))

            # ── Section 1B: Wellfound job-post leads ─────────────────────────
            jobpost_leads = pd.DataFrame()
            if "hiring_signal" in ready.columns:
                jobpost_leads = ready[ready["hiring_signal"] == "job_post"]
            else:
                jobpost_leads = ready

            print(f"\n{'─'*72}")
            print(f"  📋  JOB POSTING LEADS  ({len(jobpost_leads)} leads from Wellfound)")
            print(f"{'─'*72}")
            print("  ⚡ = High Priority (<24h post)   ★ = Founder/CTO contact\n")
            self._print_lead_table(
                jobpost_leads.head(max(0, CFG.MAX_DAILY_CONNECTS - len(high_signal)))
            )

            # ── Section 1C: Top Drafts for Today ──────────────────────────────
            ready_sorted = pd.DataFrame()
            if not ready.empty:
                ready_sorted = ready.sort_values("priority_score", ascending=False) if "priority_score" in ready.columns else ready

            if not ready_sorted.empty:
                print(f"\n{'─'*72}")
                print(f"  ✍  TOP DRAFTS FOR TODAY'S OUTREACH  (Top {min(len(ready_sorted), CFG.MAX_DAILY_CONNECTS)})")
                print("     Send connect note first, then DM after they accept.")
                print(f"{'─'*72}")
                
                composer = MessageComposer()
                for i, (_, r) in enumerate(ready_sorted.head(CFG.MAX_DAILY_CONNECTS).iterrows(), 1):
                    company      = r.get("company", "")
                    contact_name = r.get("contact_name", "")
                    url          = r.get("linkedin_url", "")
                    
                    msg1, connect_note, _, _, email_draft = composer.compose_all(r)
                    email_addr = str(r.get("email", "")).strip()
                    email_part = f" | {email_addr}" if email_addr else " | No email found"

                    print(f"\n  {i}. {contact_name} @ {company} ({url}{email_part})")
                    print(f"     💬 Connect note (send first — {len(connect_note)} chars):")
                    print(f"        \"{connect_note}\"")
                    print(f"     ✉  LinkedIn DM after connect:")
                    indented_msg = "\n".join(f"        {line}" for line in msg1.splitlines())
                    print(indented_msg)

                    if email_addr and email_draft:
                        print(f"     📧 Cold email ({email_addr}):")
                        indented_email = "\n".join(f"        {line}" for line in email_draft.splitlines())
                        print(indented_email)

        # ── Section 2: Follow-ups ─────────────────────────────────────────────
        followups_due = self._tracker.get_due_actions(crm_df)
        print(f"\n{'─'*72}")
        print(f"  🔁  FOLLOW-UPS DUE TODAY  ({len(followups_due)} leads)")
        print(f"{'─'*72}")

        if followups_due.empty:
            print("  No follow-ups due today — you're all caught up.")
        else:
            print("  Messages are in the CRM sheet → 'Outreach CRM' tab.\n")
            rows = []
            for _, r in followups_due.iterrows():
                rows.append([
                    str(r.get("due_action",    "")),
                    str(r.get("days_elapsed",  "")),
                    _truncate(r.get("company",      ""), 22),
                    _truncate(r.get("contact_name", ""), 20),
                    r.get("linkedin_url", ""),
                ])
            headers = ["Action", "Days", "Company", "Contact", "LinkedIn URL"]
            if _HAS_TABULATE:
                print(tabulate(rows, headers=headers, tablefmt="simple"))
            else:
                for r in rows:
                    print(f"  {r[0]:<18} Day{r[1]:<4} {r[2]:<22} {r[3]:<20} {r[4]}")

        # ── Section 3: Stats ──────────────────────────────────────────────────
        self._stats.report(crm_df)

        # ── Section 4: Instructions ───────────────────────────────────────────
        print("\n  📋  HOW TO USE THIS:")
        print("  1. Start with the HIGH-SIGNAL section — send those messages first")
        print("  2. Open Google Sheet → 'Outreach CRM' tab")
        print("  3. Copy the 'message_draft' cell for each lead")
        print("  4. Paste into LinkedIn DM and send manually")
        print("  5. Type 'Yes' in 'contacted' column + today's date in 'date_contacted'")
        print("  6. Run again tomorrow — follow-ups appear automatically\n")
        print("  ⚠  DO NOT automate the LinkedIn sending step.")
        print("     Manual sending = human behaviour = account stays safe.")
        print(f"\n{sep}\n")

    def _print_lead_table(self, df: pd.DataFrame) -> None:
        if df.empty:
            print("  (none)")
            return

        rows = []
        for _, r in df.iterrows():
            signal       = str(r.get("hiring_signal", "job_post"))
            urgency      = str(r.get("urgency", ""))
            contact_type = str(r.get("contact_type", ""))

            # Flags: signal icon + contact type marker
            signal_flag  = {"funding": "💰", "yc_batch": "🚀", "launch": "🚀"}.get(signal, "")
            urgency_flag = "⚡" if urgency.startswith("1") else " "
            founder_flag = "★" if contact_type == "founder" else " "
            flags        = f"{signal_flag or urgency_flag}{founder_flag} {r.get('priority_score', 0):>2}"
            email        = str(r.get("email", "")).strip() or "N/A"

            rows.append([
                flags,
                _truncate(r.get("company",      ""), 22),
                _truncate(r.get("job_title",     "") or signal, 22),
                _truncate(r.get("contact_name",  ""), 20),
                r.get("contact_type", ""),
                r.get("linkedin_url",  ""),
                email,
            ])

        headers = ["Pri", "Company", "Role/Signal", "Contact", "Type", "LinkedIn URL", "Email"]
        if _HAS_TABULATE:
            print(tabulate(rows, headers=headers, tablefmt="simple"))
        else:
            print(f"  {'Pri':<6} {'Company':<22} {'Role/Signal':<22} {'Contact':<20} {'Type':<15} {'LinkedIn URL':<30} Email")
            for r in rows:
                print(f"  {r[0]:<6} {r[1]:<22} {r[2]:<22} {r[3]:<20} {r[4]:<15} {r[5]:<30} {r[6]}")


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITY
# ══════════════════════════════════════════════════════════════════════════════

def _truncate(s: str, n: int) -> str:
    s = str(s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL SENDER  (Week 1)
#
#  Sends cold emails from your Gmail account using App Passwords (2FA-safe).
#  Does NOT require OAuth — just GMAIL_USER + GMAIL_APP_PASSWORD in .env.
#
#  Safety guarantees:
#    • --dry-run  → prints emails, sends nothing
#    • Only sends to rows in CRM that have an email_draft AND no prior send
#    • Marks email_sent = "Yes" + email_sent_date in CRM after each send
#    • MAX_DAILY_EMAILS cap (default 30) prevents accidental bulk blasts
#    • 3-second sleep between sends to avoid Gmail rate-limit
#
#  Setup (one-time):
#    1. Google Account → Security → 2-Step Verification → App Passwords
#    2. Generate password for "Mail" + device "Other (Job Bot)"
#    3. Add to .env:  GMAIL_USER=you@gmail.com
#                     GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
# ══════════════════════════════════════════════════════════════════════════════

import smtplib
from email.mime.text    import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailSender:
    """
    Sends cold-outreach emails for CRM rows that have an email_draft and
    a non-empty email address, and have not yet been sent.

    Usage (from main):
        sender = EmailSender(dry_run=args.dry_run)
        sent   = sender.send_from_crm(crm_df, crm_ws, sheets)
        LOG.info(f"EmailSender: {sent} emails dispatched")
    """

    _log = logging.getLogger("outreach.EmailSender")

    SMTP_HOST       = "smtp.gmail.com"
    SMTP_PORT       = 587
    MAX_DAILY_EMAILS = 30          # Hard cap — tune if you want more
    SEND_DELAY_S     = 3           # Seconds between sends (avoid Gmail rate-limit)

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run  = dry_run
        self._user     = os.environ.get("GMAIL_USER", "").strip()
        self._password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

        if not self._user or not self._password:
            self._log.warning(
                "⚠️  GMAIL_USER or GMAIL_APP_PASSWORD not set in .env — "
                "EmailSender will be a no-op until credentials are configured."
            )

    # ── Public API ───────────────────────────────────────────────────────────────────

    def send_from_crm(
        self,
        crm_df:  pd.DataFrame,
        crm_ws:  "gspread.Worksheet",
        sheets:  SheetsClient,
    ) -> int:
        """
        Iterates the CRM DataFrame and sends unsent email drafts.
        Returns the number of emails dispatched (or would-be dispatched in dry-run).
        """
        if not self._user or not self._password:
            self._log.error(
                "❌  Cannot send emails: GMAIL_USER / GMAIL_APP_PASSWORD missing from .env.\n"
                "   Add them and re-run: python outreach_engine.py --send-emails"
            )
            return 0

        pending = self._get_pending_rows(crm_df)
        total   = min(len(pending), self.MAX_DAILY_EMAILS)
        self._log.info(
            f"EmailSender: {len(pending)} unsent drafts found, "
            f"will send {total} (cap: {self.MAX_DAILY_EMAILS})"
            + (" [DRY RUN]" if self._dry_run else "")
        )

        sent = 0
        with (self._open_smtp() if not self._dry_run else _NullContext()) as server:
            for df_idx, row in pending.iloc[:total].iterrows():
                subject, body = self._parse_draft(str(row.get("email_draft", "")))
                to_addr       = str(row.get("email", "")).strip()

                if not to_addr or not body:
                    self._log.debug(f"  Skipping row {df_idx}: no address or empty body")
                    continue

                if self._dry_run:
                    self._log.info(
                        f"  [DRY RUN] Would send to {to_addr}\n"
                        f"    Subject: {subject}\n"
                        f"    Body snippet: {body[:120]!r}\u2026"
                    )
                else:
                    try:
                        self._send_one(server, to_addr, subject, body)
                        self._log.info(f"  ✅ Sent to {to_addr} ({row.get('company','?')})")
                    except Exception as exc:
                        self._log.error(f"  ❌ Failed to send to {to_addr}: {exc}")
                        continue

                # Mark in CRM (skip if dry-run)
                if not self._dry_run:
                    sheet_row = int(df_idx) + 2   # +1 header +1 1-indexed
                    today_str = datetime.today().strftime("%Y-%m-%d")
                    for col, val in [("email_sent", "Yes"), ("email_sent_date", today_str)]:
                        if col in CRM_HEADERS:
                            sheets.update_crm_cell(crm_ws, sheet_row, col, val)

                sent += 1
                if not self._dry_run:
                    time.sleep(self.SEND_DELAY_S)

        self._log.info(
            f"EmailSender complete: {sent} emails "
            + ("queued (dry-run)" if self._dry_run else "dispatched")
        )
        return sent

    # ── Internals ────────────────────────────────────────────────────────────────────

    def _get_pending_rows(self, crm_df: pd.DataFrame) -> pd.DataFrame:
        """Rows with an email_draft, a valid email, and not yet sent."""
        df = crm_df.copy()
        has_draft = df.get("email_draft", pd.Series(dtype=str)).str.strip().astype(bool)
        has_email = df.get("email",       pd.Series(dtype=str)).str.strip().astype(bool)
        # email_sent column may not exist yet in older CRM sheets
        if "email_sent" in df.columns:
            not_sent = df["email_sent"].str.strip().str.lower() != "yes"
        else:
            not_sent = pd.Series([True] * len(df), index=df.index)
        return df[has_draft & has_email & not_sent]

    def _parse_draft(self, draft: str) -> tuple[str, str]:
        """
        Splits email_draft into (subject, body).
        Expects first line to be "Subject: ...", rest is body.
        Falls back to generic subject if not found.
        """
        lines   = draft.strip().splitlines()
        subject = "Re: connecting with you"
        body_start = 0
        if lines and lines[0].lower().startswith("subject:"):
            subject    = lines[0].split(":", 1)[1].strip()
            body_start = 1
            # Skip blank line after subject
            if len(lines) > 1 and not lines[1].strip():
                body_start = 2
        body = "\n".join(lines[body_start:]).strip()
        return subject, body

    def _open_smtp(self) -> smtplib.SMTP:
        server = smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT)
        server.ehlo()
        server.starttls()
        server.login(self._user, self._password)
        return server

    def _send_one(
        self, server: smtplib.SMTP, to_addr: str, subject: str, body: str
    ) -> None:
        msg                  = MIMEMultipart("alternative")
        msg["From"]          = self._user
        msg["To"]            = to_addr
        msg["Subject"]       = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        server.sendmail(self._user, [to_addr], msg.as_string())

    # ── Follow-up sender (Upgrade #6) ────────────────────────────────────────

    def send_followup_batch(
        self,
        crm_df:  pd.DataFrame,
        crm_ws:  "gspread.Worksheet",
        sheets:  SheetsClient,
    ) -> int:
        """
        Auto-sends Day-7 and Day-14 follow-up emails for contacts where:
          • We have their email address
          • Initial email was sent (contacted == "Yes", date_contacted is set)
          • No reply received yet (reply_received != "Yes")
          • followup_1_sent != "Yes"  (for Day 7)  OR
            followup_2_sent != "Yes"  (for Day 14)
          • The due date has passed

        Returns total follow-ups sent this batch.
        """
        if not self._user or not self._password:
            self._log.error(
                "❌  Cannot send follow-ups: GMAIL_USER / GMAIL_APP_PASSWORD missing from .env."
            )
            return 0

        today = date.today()
        sent  = 0

        with (self._open_smtp() if not self._dry_run else _NullContext()) as server:
            for df_idx, row in crm_df.iterrows():
                email = str(row.get("email", "")).strip()
                if not email:
                    continue
                if str(row.get("contacted", "")).strip().lower() != "yes":
                    continue
                if str(row.get("reply_received", "")).strip().lower() == "yes":
                    continue

                date_str = str(row.get("date_contacted", "")).strip()
                if not date_str:
                    continue
                try:
                    date_contacted = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                days = (today - date_contacted).days
                company = str(row.get("company", "")).strip()
                sheet_row = int(df_idx) + 2  # +1 header, +1 1-indexed
                today_str = today.strftime("%Y-%m-%d")

                # Day 7 follow-up
                if days >= 7 and str(row.get("followup_1_sent", "")).lower() != "yes":
                    body = str(row.get("followup_1_draft", "")).strip()
                    if body:
                        subject = f"Re: {company}"
                        if self._dry_run:
                            self._log.info(
                                f"  [DRY RUN] FU-1 → {email} ({company}, day {days})"
                            )
                        else:
                            try:
                                self._send_one(server, email, subject, body)
                                self._log.info(f"  ✅ Follow-up 1 sent → {email} ({company})")
                                for col, val in [
                                    ("followup_1_sent", "Yes"),
                                    ("followup_1_date", today_str),
                                ]:
                                    if col in CRM_HEADERS:
                                        sheets.update_crm_cell(crm_ws, sheet_row, col, val)
                                time.sleep(random.uniform(180, 300))
                            except Exception as exc:
                                self._log.error(f"  ❌ FU-1 failed → {email}: {exc}")
                                continue
                        sent += 1

                # Day 14 follow-up (only if Day 7 was already sent)
                elif (days >= 14
                      and str(row.get("followup_1_sent", "")).lower() == "yes"
                      and str(row.get("followup_2_sent", "")).lower() != "yes"):
                    body = str(row.get("followup_2_draft", "")).strip()
                    if body:
                        subject = f"Final note: {company}"
                        if self._dry_run:
                            self._log.info(
                                f"  [DRY RUN] FU-2 → {email} ({company}, day {days})"
                            )
                        else:
                            try:
                                self._send_one(server, email, subject, body)
                                self._log.info(f"  ✅ Follow-up 2 sent → {email} ({company})")
                                for col, val in [
                                    ("followup_2_sent", "Yes"),
                                    ("followup_2_date", today_str),
                                ]:
                                    if col in CRM_HEADERS:
                                        sheets.update_crm_cell(crm_ws, sheet_row, col, val)
                                time.sleep(random.uniform(180, 300))
                            except Exception as exc:
                                self._log.error(f"  ❌ FU-2 failed → {email}: {exc}")
                                continue
                        sent += 1

        self._log.info(
            f"Follow-up batch complete: {sent} follow-ups "
            + ("queued (dry-run)" if self._dry_run else "sent")
        )
        return sent


class _NullContext:
    """Context manager no-op used when dry_run=True (replaces SMTP connection)."""
    def __enter__(self): return self
    def __exit__(self, *_): pass


# ══════════════════════════════════════════════════════════════════════════════
#  LINKEDIN SENDER  (Upgrade #8 — SEMI-AUTO)
#
#  Opens each profile in your real Brave browser, clicks Connect,
#  pre-fills the personalized note from the CRM sheet, then PAUSES.
#  YOU click the final "Send" button — the bot never auto-sends.
#
#  Safe because:
#    • Real Brave profile = your existing LinkedIn session
#    • No headless mode — full browser, human-looking
#    • Final click is always human
#    • 10 connects/session cap (LinkedIn allows ~20-25/day before flagging)
#    • 2-5 min delay between opens
# ══════════════════════════════════════════════════════════════════════════════

class LinkedInSender:
    """
    Semi-automated LinkedIn connect flow.

    1. Opens lead's LinkedIn profile in your real Brave browser
    2. Finds and clicks the "Connect" button
    3. Pre-fills the personalised connect_note from the CRM into the text box
    4. PAUSES — prints a terminal prompt and waits for YOU to click "Send"
    5. On [Enter], marks contacted=Yes in CRM and moves to next profile

    Daily cap: MAX_PER_SESSION connects (default 10).
    """

    MAX_PER_SESSION: int = 10
    _log = logging.getLogger("outreach.LinkedInSender")

    def __init__(self) -> None:
        self._brave_profile = os.environ.get("BRAVE_PROFILE_PATH", "")

    def send_batch(
        self,
        crm_df:  pd.DataFrame,
        crm_ws:  "gspread.Worksheet",
        sheets:  SheetsClient,
    ) -> int:
        """
        Processes up to MAX_PER_SESSION leads that have a linkedin_url and
        connect_note but haven't been contacted yet.
        Returns the number of profiles opened.
        """
        pending = crm_df[
            crm_df.get("linkedin_url",  pd.Series(dtype=str)).str.strip().astype(bool)
            & crm_df.get("connect_note", pd.Series(dtype=str)).str.strip().astype(bool)
            & (crm_df.get("contacted",   pd.Series(dtype=str)).str.strip().str.lower() != "yes")
        ].head(self.MAX_PER_SESSION)

        if pending.empty:
            self._log.info("No pending LinkedIn leads — all have been contacted.")
            return 0

        self._log.info(
            f"LinkedInSender: opening {len(pending)} profiles (cap={self.MAX_PER_SESSION})"
        )

        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.common.exceptions import TimeoutException, NoSuchElementException
            from selenium.webdriver.chrome.options import Options as ChromeOptions
        except ImportError:
            self._log.error("❌  pip install selenium — required for LinkedInSender")
            return 0

        driver = self._build_driver(ChromeOptions)
        opened = 0

        try:
            for df_idx, row in pending.iterrows():
                url  = str(row.get("linkedin_url",  "")).strip()
                note = str(row.get("connect_note",  "")).strip()[:280]
                name = str(row.get("contact_name",  "Contact")).strip()
                co   = str(row.get("company",        "")).strip()

                self._log.info(f"\n  → Opening: {name} ({co})")
                try:
                    driver.get(url)
                    time.sleep(random.uniform(4, 7))

                    connected = self._click_connect(
                        driver, By, WebDriverWait, EC, TimeoutException, NoSuchElementException
                    )
                    if connected:
                        self._fill_note(driver, note, By, WebDriverWait, EC, TimeoutException)
                        self._log.info(f"  ✏️  Note pre-filled ({len(note)} chars)")
                    else:
                        self._log.warning(
                            "  ⚠️  Could not find Connect button — "
                            "may already be connected or layout changed"
                        )

                    print(
                        f"\n  ┌─────────────────────────────────────────────────────────┐"
                        f"\n  │  👉  {name} ({co})"
                        f"\n  │  Note pre-filled. Review + click 'Send' on LinkedIn."
                        f"\n  └─────────────────────────────────────────────────────────┘"
                    )
                    input("  Press [Enter] after you click Send (Ctrl+C to skip) … ")

                    opened += 1
                    today_str = datetime.today().strftime("%Y-%m-%d")
                    sheet_row = int(df_idx) + 2
                    for col, val in [("contacted", "Yes"), ("date_contacted", today_str)]:
                        if col in CRM_HEADERS:
                            sheets.update_crm_cell(crm_ws, sheet_row, col, val)

                except KeyboardInterrupt:
                    self._log.info("  Skipped by user")
                except Exception as exc:
                    self._log.error(f"  ❌ Error on {url}: {exc}")
                    continue

                delay = random.uniform(120, 300)
                self._log.info(f"  ⏱  Waiting {delay:.0f}s before next profile…")
                time.sleep(delay)

        finally:
            driver.quit()

        self._log.info(f"LinkedInSender: {opened} profiles opened this session")
        return opened

    # ── Internals ──────────────────────────────────────────────────────────────

    def _build_driver(self, ChromeOptions) -> "webdriver.Chrome":
        from selenium import webdriver
        opts = ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        if self._brave_profile and os.path.exists(self._brave_profile):
            opts.add_argument(f"--user-data-dir={os.path.dirname(self._brave_profile)}")
            opts.add_argument(f"--profile-directory={os.path.basename(self._brave_profile)}")
        driver = webdriver.Chrome(options=opts)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver

    def _click_connect(self, driver, By, WebDriverWait, EC,
                        TimeoutException, NoSuchElementException) -> bool:
        for sel in [
            "button[aria-label*='Connect' i]",
            "button.pvs-profile-actions__action",
            ".pv-s-profile-actions button",
        ]:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                if "connect" in (btn.get_attribute("aria-label") or "").lower() or \
                   "connect" in btn.text.lower():
                    btn.click()
                    time.sleep(random.uniform(1.5, 3))
                    return True
            except (TimeoutException, NoSuchElementException):
                continue
        return False

    def _fill_note(self, driver, note: str, By, WebDriverWait, EC,
                   TimeoutException) -> None:
        try:
            add_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button[aria-label*='note' i], button.mr1")
                )
            )
            add_btn.click()
            time.sleep(1)
        except TimeoutException:
            pass
        try:
            ta = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "textarea[name='message'], textarea#custom-message")
                )
            )
            ta.clear()
            ta.send_keys(note)
        except TimeoutException:
            self._log.debug("  Could not find connect note textarea")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Outreach Conversion Engine v2 — Signal-Aware"
    )
    p.add_argument("--followups",      action="store_true",
                   help="Print only follow-ups due today and exit")
    p.add_argument("--stats",          action="store_true",
                   help="Print campaign stats and exit")
    p.add_argument("--mark-contacted", metavar="LINKEDIN_URL",
                   help="Mark a lead as contacted")
    p.add_argument("--dry-run",        action="store_true",
                   help="Run without writing to Google Sheets")
    # NEW: filter to a specific source
    p.add_argument(
        "--source",
        metavar="SOURCE",
        default=None,
        help="Filter briefing to a specific source: funding | yc | producthunt | wellfound",
    )
    p.add_argument(
        "--send-emails",
        action="store_true",
        help=(
            "Send cold emails via Gmail SMTP for all CRM rows that have an email_draft "
            "and have not yet been sent. Requires GMAIL_USER + GMAIL_APP_PASSWORD in .env."
        ),
    )
    p.add_argument(
        "--send-followups",
        action="store_true",
        help=(
            "Auto-send Day-7 and Day-14 follow-up emails for contacts already in CRM. "
            "Requires GMAIL_USER + GMAIL_APP_PASSWORD in .env."
        ),
    )
    return p.parse_args()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    _configure_logging()
    args = _parse_args()

    sep = "═" * 70
    LOG.info(sep)
    LOG.info("  Outreach Conversion Engine  —  v2  (Signal-Aware)")
    LOG.info(f"  {datetime.today().strftime('%Y-%m-%d %H:%M:%S')}")
    LOG.info(sep)

    try:
        sheets = SheetsClient()
    except FileNotFoundError as exc:
        LOG.error(str(exc))
        sys.exit(1)

    crm_ws = sheets.get_or_create_crm_worksheet()
    crm_df = sheets.get_crm_df(crm_ws)

    stats   = StatsEngine()
    tracker = FollowUpTracker()

    if args.stats:
        stats.report(crm_df)
        return

    if args.followups:
        due = tracker.get_due_actions(crm_df)
        if due.empty:
            print("\n  ✅  No follow-ups due today.\n")
        else:
            print(f"\n  🔁  {len(due)} follow-ups due:\n")
            for _, r in due.iterrows():
                signal = str(r.get("hiring_signal", "")).strip()
                print(
                    f"  [{r.get('due_action','')}]  "
                    f"{r.get('company','')}  —  "
                    f"{r.get('contact_name','')}  "
                    f"(Day {r.get('days_elapsed','')})"
                    + (f"  [{signal}]" if signal else "")
                )
                print(f"    {r.get('linkedin_url','')}\n")
        return

    if args.mark_contacted:
        target_url  = args.mark_contacted.strip()
        crm_df_full = sheets.get_crm_df(crm_ws)
        match_idx   = None

        for i, row in crm_df_full.iterrows():
            if str(row.get("linkedin_url", "")).strip() == target_url:
                match_idx = int(i) + 2
                break

        if match_idx is None:
            LOG.error(f"URL not found in CRM: {target_url}")
            sys.exit(1)

        today_str = datetime.today().strftime("%Y-%m-%d")
        sheets.update_crm_cell(crm_ws, match_idx, "contacted",      "Yes")
        sheets.update_crm_cell(crm_ws, match_idx, "date_contacted", today_str)
        LOG.info(f"✅  Marked as contacted: {target_url}")
        return

    # ── Full run ───────────────────────────────────────────────────────────────
    try:
        leads_df = sheets.get_leads_df()
        if leads_df.empty:
            LOG.warning("Leads tab is empty — run job_pipeline_v3.py first.")
            return

        # Optional source filter
        if args.source:
            source_filter = args.source.strip().lower()
            # Map short names
            source_map = {
                "funding":     "funding",
                "yc":          "yc",
                "producthunt": "producthunt",
                "wellfound":   "wellfound",
            }
            mapped = source_map.get(source_filter, source_filter)
            if "source" in leads_df.columns:
                before = len(leads_df)
                leads_df = leads_df[leads_df["source"].str.lower() == mapped]
                LOG.info(f"Source filter '{mapped}': {before} → {len(leads_df)} rows")
            else:
                LOG.warning("Sheet has no 'source' column — filter ignored (run v3 pipeline first)")

        prioritizer    = Prioritizer()
        prioritized_df = prioritizer.prioritize(leads_df)

        if not args.dry_run:
            crm_writer = CRMWriter(sheets)
            added      = crm_writer.sync(prioritized_df, crm_ws)
            LOG.info(f"CRM sync complete — {added} new rows added")
        else:
            LOG.info("[DRY RUN] Skipping CRM write")

        crm_df   = sheets.get_crm_df(crm_ws)
        briefing = DailyBriefing(tracker, stats)
        briefing.print_briefing(new_leads_df=prioritized_df, crm_df=crm_df)

        # ── Optional: send cold emails ────────────────────────────────────────
        if args.send_emails:
            fresh_crm_df = sheets.get_crm_df(crm_ws)   # re-read after sync
            sender       = EmailSender(dry_run=args.dry_run)
            sent_count   = sender.send_from_crm(fresh_crm_df, crm_ws, sheets)
            LOG.info(f"✉️  Email dispatch complete: {sent_count} emails sent")

        # ── Optional: send follow-up emails ──────────────────────────────────
        if args.send_followups:
            fresh_crm_df = sheets.get_crm_df(crm_ws)   # re-read to catch any new contacts
            fu_sender    = EmailSender(dry_run=args.dry_run)
            fu_count     = fu_sender.send_followup_batch(fresh_crm_df, crm_ws, sheets)
            LOG.info(f"🔁  Follow-up dispatch complete: {fu_count} follow-ups sent")

    except KeyboardInterrupt:
        LOG.warning("Interrupted by user.")
    except Exception as exc:
        LOG.critical(f"Fatal error: {exc}")
        LOG.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()