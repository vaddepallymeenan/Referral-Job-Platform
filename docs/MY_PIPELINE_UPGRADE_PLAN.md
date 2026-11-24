# MY PIPELINE — Personal Upgrade Plan

> Goal: Match Sam+Pipeline rate (~1.3 offers/month) with <3 hrs/week manual work.
> Only do manual where manual is absolutely necessary.

---

## MY ACTUAL MANUAL WORKFLOW TODAY (IITK aggressive job search)

```
1. LinkedIn — send connect requests to founders/hiring managers
2. Wellfound/Naukri/Instahyre — apply to jobs, update Naukri profile daily
3. Find career portals — Google "company careers", apply through Greenhouse/Lever
4. JobCode18 — shares career portal redirect links (has a website, not just WhatsApp)

SEARCHING (10+ hrs/week — pipeline should eliminate this):
  → Scrolling Wellfound for 30 min finding relevant jobs
  → Browsing Naukri search results, filtering by startup/AI/ML
  → Googling "company name careers" for 20 companies
  → Reading JobCode18 links one by one, checking relevance
  → Searching LinkedIn for "AI engineer hiring Bengaluru"
  → Researching each company before applying
  → Finding the right person to message on LinkedIn

CLICKING (3-4 hrs/week — this stays manual, pipeline makes it faster):
  → Clicking "Apply" on Wellfound (2 min each)
  → Filling Greenhouse/Lever forms (3-5 min each)
  → Sending LinkedIn connect requests with personalized notes (2 min each)
  → Updating Naukri profile (small daily edit to stay on top)
  → Responding to replies, scheduling calls
```

---

## WHERE THE GAP IS RIGHT NOW

```
What Sam does that my pipeline DOESN'T:

1. APPLIES through ATS portals     → 150 apps/month → 22 ATS passes → 12 calls
   My pipeline:                     → 0 applications → 0 ATS passes → 0 calls

2. Uses 6+ platforms               → Wellfound + LinkedIn + Instahyre + Naukri + careers pages
   My pipeline:                     → Wellfound + YC + YourStory RSS + Inc42 RSS

3. Applies outside the filter box   → Series B, 100+ employees, any promising company
   My pipeline:                     → Seed/A only, 10-80 employees, must_have_tech filter

Pipeline produces a SPREADSHEET. Sam produces APPLICATIONS.
Fix that and I win — same volume at 1/6th the time.
```

---

## CURRENT PIPELINE NUMBERS (from actual code)

```
Per run:
  MAX_COMPANIES_TO_ENRICH = 40          (line 169)
  CONTACTS_PER_COMPANY = 2             (line 161)
  Sources: wellfound, yc, yourstory, funding  (line 2042-2047)
  SeenCompaniesCache = 180 days         (line 1536 — comments say 14, code does 180)

Per month (3-4 runs):
  New contacts in sheet: 60-80
  LinkedIn invites sent (manual): 60-70
  Accepts: 25-28
  Replies: 4-5
  Calls: 2
  Tech rounds: 1
  Offers: 0.27/month

Sam's numbers:
  Applications: 150/month
  Calls: 12/month
  Tech rounds: 6/month
  Offers: 1.0/month
```

---

## BAN-SAFETY GUIDE

### WHAT WILL GET YOU BANNED — DO NOT AUTOMATE THESE ROUGHLY

```
❌ LinkedIn auto-send connects/messages
   → LinkedIn detects Selenium/puppeteer. Even "semi-auto" with human click
     gets flagged because the browser fingerprint is automated.
   → Result: Account restricted, can't send invites for 1-4 weeks.
   → This kills your ENTIRE outreach channel.

❌ Wellfound auto-apply (without separate session & fallback)
   → Wellfound already has bot detection. Your pipeline's own scraper
     triggers _run_brave_fallback() when it gets blocked (lines 770-776).
   → Auto-clicking "Apply" from the same Selenium session that scraped = instant flag.
   → Result: Account banned, lose access to job listings entirely.
   → MITIGATION: Wellfound auto-apply must use a completely separate, clean Brave browser profile with human delays and an immediate fallback to manual apply if bot detection triggers.

❌ Naukri/Instahyre auto-apply
   → Both have CAPTCHAs, rate limits, and login-session tracking.
   → Automated form submission from headless browser = flagged in hours.
   → ALWAYS keep Naukri/Instahyre apply completely manual using the sheet links.

❌ Mass-sending identical LinkedIn messages
   → LinkedIn's spam detection catches identical or near-identical messages
     sent to 10+ people. Your connect note templates will trigger this.
   → Result: "You've been restricted from sending invitations."
```

### WHAT CANNOT GET YOU BANNED — BUILD AND AUTOMATE FREELY

```
✅ Discovery via API calls (Brave Search API)
   → You're calling an API you pay for. No platform is watching.
   → This is what the pipeline already does well.

✅ Email outreach (your own email, no platform controls it)
   → You own your Gmail/domain. Nobody can ban you for sending emails.
   → The pipeline finds contacts but barely uses email. This is the unlocked channel.

✅ Careers page applications (individual company websites)
   → Each company runs their own careers site (Greenhouse, Lever, Workable, custom).
   → No central platform is watching across all of them.
   → Each application is to a DIFFERENT domain — no pattern for anyone to detect.

✅ RSS/feed monitoring (YourStory, Inc42)
   → Reading public RSS feeds. Not scraping. Not logged in.

✅ Google Sheets / SQLite operations
   → Your own data. Nobody cares.
```

### THE BALANCED APPROACH (MAXIMUM RESULTS WITH ZERO PROFILE BANS)

```
✅ SAFE TO AUTOMATE:
  → Brave Search API calls (you pay for it, no platform watching)
  → Email outreach via your own Gmail SMTP (you own the mailbox)
  → Careers page auto-apply (each company's OWN site — Greenhouse, Lever, Workable)
     → decentralized, no central platform watching across domains
     → each application is to a DIFFERENT domain
  → RSS/feed monitoring (YourStory, Inc42)
  → Scraping JobCode18 website (public site, just extracting links)
  → Google Sheets / SQLite operations (your own data)

⚠️ USE WITH EXTREME CAUTION (Safety Precautions Built-In):
  → Wellfound auto-apply (Brave profile + 30-90s delays + bot detection fallback)
     → if bot detected, save the link for manual apply in sheet
  → Semi-auto LinkedIn Connects (opens profile, human clicks Send)
     → MAX 10 per session, 2-5 min gaps, unique personalized templates
  → Naukri profile micro-edit (toggle a period in headline once/day to trigger refresh)
```

---

## THE 8 UPGRADES (ranked by impact)

### 1. AUTO-APPLY ENGINE — closes 70% of the gap

**The problem:** Pipeline finds 40 companies/run but never applies. Sam's entire edge is clicking "Apply" 150 times.

**The fix:** New file `auto_applier.py`. For every company the pipeline finds:
1. For all companies → find careers page → auto-apply through Greenhouse/Lever (SAFE — decentralized)
2. If source=wellfound → navigate to source_url → click Apply (use existing Brave profile, use caution)

**What I automate vs what stays manual:**
```
AUTOMATED (careers pages — SAFE):
  ✓ Finding careers page URL (Brave search)
  ✓ Navigating to Greenhouse/Lever/Workable apply page
  ✓ Filling standard form fields (name, email, phone, LinkedIn)
  ✓ Uploading resume PDF
  ✓ Logging application in CRM

AUTOMATED WITH CAUTION (Wellfound):
  ✓ Navigate to Wellfound listing via Brave profile
  ✓ Click Apply → fill form → submit
  ✓ Human-speed delays (30-90s between applications)
  → If Wellfound flags: auto-fall back to just saving the link for manual apply

MANUAL (absolute necessary):
  ✗ Review tailored resume 1x/week before batch runs
  ✗ Handle CAPTCHA if it appears (rare on careers pages)
  ✗ Custom cover letter fields (use LLM-generated template)
  ✗ Naukri/Instahyre apply (CAPTCHAs — use links from sheet)
```

**Why careers page auto-apply is SAFE (decentralized):**
```
Each company runs their own careers site — Greenhouse, Lever, Workable, custom.
No central platform is watching you apply across 40 different company websites.
Each application is a single visit to a single domain.

  → You visit sarvam.ai/careers ONCE, apply ONCE, leave
  → You visit devrev.ai/careers ONCE, apply ONCE, leave  
  → Each company only sees 1 visit from you. That's what humans do.
  → There's no Wellfound/Naukri watching across all of them.

Why Wellfound auto-apply needs caution:
  → One platform, one account, one bot detector watching everything you do.
  → BUT: Brave profile + human delays (30-90s) = usually safe.
  → Fallback: if flagged, save the link for manual apply.
```

**Code sketch:**
```python
class AutoApplier:
    def __init__(self):
        self.driver = _build_shared_driver()  # existing function
        self.profile = load_candidate_profile()  # from .env

    def run(self, companies_df: pd.DataFrame, resume_path: str):
        applied = 0
        for _, row in companies_df.iterrows():
            company = row["company"]
            source = row["source"]
            
            # Track 1: Careers page apply (SAFE — decentralized)
            domain = self._find_domain(company)
            if domain:
                careers_url = self._find_careers_page(domain)
                if careers_url:
                    job_url = self._find_matching_job(
                        careers_url, row.get("job_title", "")
                    )
                    if job_url:
                        success = self._apply(job_url, resume_path)
                        if success:
                            applied += 1
            
            # Track 2: Wellfound direct apply (use caution)
            if source == "wellfound" and row.get("source_url"):
                try:
                    self._apply_wellfound(row["source_url"])
                except BotDetectedError:
                    # Fallback: save link for manual apply
                    self._save_manual_link(row)
            
            _human_delay(120, 300)  # 2-5 min between applications (natural human speed)
        
        return applied

    def _find_careers_page(self, domain: str) -> str | None:
        """Brave API: 'company name careers jobs apply site:greenhouse.io OR
        site:lever.co OR site:workable.com OR site:company.com/careers'"""
        pass

    def _find_matching_job(self, careers_url: str, target_role: str) -> str | None:
        """Scrape careers page, find job matching target role keywords."""
        pass

    def _apply(self, job_url: str, resume_path: str) -> bool:
        """Fill application form with profile data + resume.
        Greenhouse/Lever forms have standard structure:
        Name, email, phone, resume upload, optional cover letter."""
        pass

    def _apply_wellfound(self, url: str):
        """Navigate to Wellfound listing → click Apply → fill form"""
        pass

    def _save_manual_link(self, row):
        """Save link to Sheet for manual apply (Wellfound bot detection fallback)"""
        pass
```

**Form filling strategy:**
```
Standard fields (auto-fill from profile):
  ✓ Name, email, phone, LinkedIn URL
  ✓ Upload tailored resume PDF
  ✓ Cover letter (LLM-generated, job-specific)
  ✓ Years of experience, current company
  ✓ Location, work authorization

Non-standard fields:
  ✓ If text field: LLM generates answer based on JD + profile
  ✓ If dropdown: match closest option to user data
  ✗ If CAPTCHA: flag for manual (rare on Greenhouse/Lever)
```

**Impact:**
```
Careers page auto-apply:    18-24 applications/month (automated, zero ban risk)
Wellfound auto-apply:       15-20 applications/month (Brave profile, human delays)
Wellfound fallback (manual): 5-10 (if bot detected, use link from sheet)
TOTAL:                      38-54 ATS applications/month

At 15% ATS pass: +6-8 recruiter callbacks
At 50% tech round: +3-4 tech rounds
Net: +0.5 offers/month
```

---

### 2. CAREER PORTAL URL FINDER — all links in one sheet

**What I do now:** Google "company name careers" → click through → find the listing. 5-10 min per company just FINDING.

**What the pipeline does:** For every company discovered, automatically find ALL apply links across platforms and put them in one row.

```python
class CareerPortalFinder:
    """
    For each company, finds and stores:
    1. Careers page URL (greenhouse/lever/workable/custom)
    2. Specific job listing URL matching target role
    3. Wellfound listing URL
    4. Naukri listing URL
    5. Instahyre listing URL
    
    ALL stored in Google Sheet as clickable links.
    """
    
    def find_all_links(self, company: str, job_title: str) -> dict:
        links = {}
        
        # Careers page
        careers_q = f'"{company}" careers jobs apply'
        links["careers_url"] = self._brave_search(careers_q, [
            "greenhouse.io", "lever.co", "workable.com", 
            "jobs.ashbyhq.com", "/careers", "/jobs"
        ])
        
        # Specific role listing
        if job_title:
            role_q = f'"{company}" "{job_title}" apply'
            links["role_url"] = self._brave_search(role_q)
        
        # Wellfound listing
        links["wellfound_url"] = self._brave_search(
            f'site:wellfound.com "{company}"'
        )
        
        # Naukri listing
        links["naukri_url"] = self._brave_search(
            f'site:naukri.com "{company}" AI OR ML'
        )
        
        # Instahyre listing
        links["instahyre_url"] = self._brave_search(
            f'site:instahyre.com "{company}"'
        )
        
        return links
```

**New columns in Google Sheet (I just click and apply):**

| Company | Careers Page | Wellfound | Naukri | Instahyre | LinkedIn Contact |
|---|---|---|---|---|---|
| Sarvam AI | [CLICK](careers) | [APPLY](wf) | — | — | [CONNECT](li) |
| DevRev | [CLICK](careers) | [APPLY](wf) | [APPLY](nk) | [APPLY](ih) | [CONNECT](li) |

---

### 3. JOBCODE18 WEBSITE SCRAPER — new discovery source

**What I do now:** Get links from JobCode18 WhatsApp group manually.

**What the pipeline does:** Scrape JobCode18's website directly — extract career portal redirect links, filter for AI/ML roles.

```python
class JobCode18Source:
    """
    Scrapes jobcode18 website for career portal redirect links.
    These are direct links to Greenhouse/Lever/company career pages.
    Filters for AI/ML/Data Science roles matching user criteria.
    """
    _log = logging.getLogger("pipeline.JobCode18Source")
    
    def fetch_jobs(self) -> list[dict]:
        """
        Scrape the JobCode18 website:
        1. Find all job listing links
        2. Follow redirect URLs to actual career portal pages
        3. Extract: company name, role title, apply URL
        4. Filter for AI/ML keywords
        """
        driver = _build_shared_driver()
        # Navigate to JobCode18 website
        # Extract all job links
        # Follow redirects to get actual Greenhouse/Lever URLs
        # Filter by role keywords: AI, ML, machine learning, data science
        
        jobs = []
        for link in self._extract_links(driver):
            final_url = self._follow_redirect(link)
            role_info = self._parse_job_page(final_url)
            
            if self._matches_criteria(role_info):
                jobs.append({
                    "company": role_info["company"],
                    "role": role_info["title"],
                    "apply_url": final_url,
                    "source": "jobcode18",
                })
        
        driver.quit()
        return jobs
    
    def _matches_criteria(self, role_info: dict) -> bool:
        """Check if role matches AI/ML keywords."""
        keywords = ["ai", "ml", "machine learning", "data scien", 
                     "mlops", "deep learning", "nlp", "computer vision"]
        title = role_info.get("title", "").lower()
        return any(kw in title for kw in keywords)
```

**Impact:** +15-25 fresh career portal links/month that I wouldn't have found otherwise. These are DIRECT APPLY links — highest conversion.

---

### 4. ADD INSTAHYRE + NAUKRI SOURCES — closes 20% of gap

**The problem:** Pipeline has 4 sources. Sam uses 6+. `instahyre` already has `source_caps` (line 2482) but no class.

**The fix:** Add two source classes to `job_pipeline_v2.py`.

```python
# Both use Brave Search API (already have) — no new scraping infrastructure

class InstahyreSource:
    """
    Uses Brave Search API to find companies posting on Instahyre.
    Does NOT log in to Instahyre. Does NOT apply through Instahyre.
    Only discovers company names → feeds them to careers page auto-apply, 
    email enricher, and manual sheet row for user clicks.
    """
    _log = logging.getLogger("pipeline.InstahyreSource")
    
    def fetch_companies(self) -> list[Company]:
        queries = [
            'site:instahyre.com "AI engineer" OR "ML engineer" Bengaluru',
            'site:instahyre.com "data scientist" OR "MLOps" India',
            'site:instahyre.com "machine learning" startup hiring',
        ]
        # Use existing Brave API + _extract_company_from_slug_or_headline()
        # Return list[Company] with hiring_signal="job_post"
        pass

class NaukriSource:
    """
    Uses Brave Search API to discover companies listing on Naukri.
    Does NOT log in to Naukri. Does NOT auto-apply through Naukri.
    Discovers company names → feeds them to safe automated channels (email/careers page).
    """
    _log = logging.getLogger("pipeline.NaukriSource")
    
    def fetch_companies(self) -> list[Company]:
        queries = [
            'site:naukri.com "AI engineer" startup Bengaluru 2026',
            'site:naukri.com "machine learning engineer" startup India',
        ]
        pass

# Add to _ALL_SOURCES dict (line 2042):
_ALL_SOURCES = {
    "wellfound":  WellfoundSource,
    "yc":         YCSource,
    "yourstory":  YourStorySource,
    "funding":    FundingSource,
    "instahyre":  InstahyreSource,   # NEW
    "naukri":     NaukriSource,       # NEW
    "jobcode18":  JobCode18Source,    # NEW
}
```

**What stays manual:** Nothing. Fully automated discovery.

**Impact:** +15-25 fresh companies/month. These have active job postings → higher apply conversion.

---

### 5. EMAIL AUTO-SEND — the fully automatable outreach channel

**Why email is the best channel to automate:** You own your mailbox. No LinkedIn caps. No Wellfound bot detection. No account bans. Send 30/day safely.

**Current problem:** Pipeline finds ~80 contacts/month but only ~20 get valid emails (30% hit rate via Brave). The other 60 contacts only have LinkedIn URLs — which forces manual copy-paste into LinkedIn with a strict 5/day invite cap and high ban risk. This represents hours of grunt work that stalls outreach throughput.

**The fix:** Upgrade email discovery to a 60-70% hit rate, making email the primary, fully automated outreach channel.

```python
class EmailEnricher:
    """
    For each company, find founder/CTO email through multiple methods.
    Run AFTER contact discovery, BEFORE outreach.
    Push hit rate from 30% to 65%.
    """
    
    def enrich(self, contacts: list) -> list:
        for contact in contacts:
            if contact.get("email"):
                continue
            
            company = contact["source_company"]
            name = contact["contact_name"]
            
            # Method 1: Hunter.io (free: 25/month, paid $49: 500/month)
            email = self._hunter_find(company, name)
            
            # Method 2: Pattern guess + SMTP verify
            if not email:
                domain = self._find_domain(company)
                if domain:
                    email = self._guess_and_verify(name, domain)
            
            # Method 3: Brave search for public email
            if not email:
                email = self._brave_search_email(name, company)
            
            if email:
                contact["email"] = email
        return contacts
    
    def _hunter_find(self, company: str, name: str) -> str | None:
        """Hunter.io API: find email by name + company domain.
        Free tier: 25 searches/month. Paid ($49/mo): 500/month — worth it."""
        pass
    
    def _guess_and_verify(self, name: str, domain: str) -> str | None:
        """
        Try common patterns and verify with SMTP RCPT TO
        (doesn't send anything, just checks if mailbox exists):
          first@domain.com
          first.last@domain.com
          f.last@domain.com
          firstlast@domain.com
        """
        pass
    
    def _brave_search_email(self, name: str, company: str) -> str | None:
        """Brave search: '"name" "company" email OR "@company.com"'"""
        pass

class EmailSender:
    """
    Auto-send cold emails via Gmail SMTP.
    Uses existing _compose_email_draft() from MessageComposer.
    Spacing: 1 email every 3-5 min (looks human to Gmail).
    Daily cap: 30 emails/day (Gmail allows 500, but stay low for deliverability).
    """
    
    MAX_PER_DAY = 30
    
    def send_batch(self, crm_df):
        unsent = crm_df[
            (crm_df["email"].str.strip() != "") &
            (crm_df["contacted"] != "Yes")
        ].head(self.MAX_PER_DAY)
        
        for _, row in unsent.iterrows():
            email_body = row["email_draft"]  # Already generated by MessageComposer
            to_addr = row["email"]
            subject = self._extract_subject(email_body)
            
            self._send_via_smtp(to_addr, subject, email_body)
            time.sleep(random.uniform(180, 300))  # 3-5 min between sends
            
            # Mark as contacted in CRM
            self._update_crm(row, "email")
```

**What the pipeline does with email after enrichment:**
```
Discovery → Enrichment → EmailEnricher → EmailSender (auto-send)
                                ↓
                    Contacts feed into BOTH:
                    1. EmailEnricher → auto-send cold email (SAFE — your mailbox)
                    2. CareersPageApplier → auto-apply on their website (SAFE — decentralized)
                    3. Google Sheet → you manually send LinkedIn invite (SAFE — human action)
```

**Impact:**
```
Before:  20 emails/month, 0 auto-sent
After:   50-60 emails/month, all auto-sent
At 15% reply: 8-9 replies (up from 2-3)
At 45% call: 4 calls (up from 1)
Net: +0.5 offers/month — ZERO manual work on this channel
```

---

### 6. WIDEN FILTER BOX — instant 40% more companies

**The problem:** `TARGET_COMPANY_CRITERIA` (line 208-215) is too restrictive.

**The fix:** Edit 3 numbers in `job_pipeline_v2.py`:

```python
# CURRENT:
TARGET_COMPANY_CRITERIA = {
    "employee_range": (10, 80),      # misses good 100-person companies
    "stages": ["Seed", "Series A", "Pre-Series A", "Pre-Seed", "Angel"],
    "founded_after": 2020,            # misses 2018-2019 companies
    "funding_range_usd_m": (0.5, 5.0)
}

# UPGRADED:
TARGET_COMPANY_CRITERIA = {
    "employee_range": (5, 200),       # wider net
    "stages": ["Seed", "Series A", "Pre-Series A", "Pre-Seed", "Angel", "Series B"],
    "founded_after": 2018,            # 2 more years of companies
    "funding_range_usd_m": (0.3, 10.0)
}
```

**Impact:** Pool goes from ~250 to ~400+. Delays pool exhaustion by ~2 months.

---

### 7. FIX SEENCOMPANIESCACHE — pool lasts 6x longer

**The problem:** Code at line 1536 uses `180 * 24 * 3600` (180 days).

**The fix:**

```python
# Line 1536 — change 180 to 30:
cutoff = time.time() - (30 * 24 * 3600)  # 30 days instead of 180

# Also fix stale comments:
# Line 9:    says "14-day" → change to "30-day"
# Line 3225: says "last 14 days" → change to "last 30 days"
# Line 1516: says "Permanently skip" → change to "Skip for 30 days"
```

**Impact:** Companies re-enter pipeline after 30 days.

---

### 8. SEMI-AUTO LINKEDIN SENDER + NAUKRI PROFILE UPDATER

**LinkedIn semi-auto (use with caution):**
```python
class LinkedInSender:
    """
    Opens profile in Brave, pre-fills connect note from CRM.
    Human clicks final Send. MAX 10 per session, 2-5 min gaps.
    """
    MAX_PER_SESSION = 10

    def send_batch(self, crm_df):
        unsent = crm_df[
            (crm_df["contacted"] != "Yes") & 
            (crm_df["linkedin_url"].str.strip() != "")
        ].head(self.MAX_PER_SESSION)
        
        driver = _build_shared_driver()
        for _, row in unsent.iterrows():
            driver.get(row["linkedin_url"])
            _human_delay(3, 6)
            # Pre-fill connect note
            # WAIT for human to review and click Send
            input("  → Review and click Send, then press Enter...")
            _human_delay(120, 300)  # 2-5 min between sends
        driver.quit()
```

**Naukri profile auto-updater:**
```python
class NaukriProfileUpdater:
    """
    Daily micro-edit to Naukri profile (add/remove period from headline).
    Keeps profile at top of recruiter search results.
    """
    def update(self):
        driver = _build_shared_driver()  # uses BRAVE_PROFILE_PATH
        driver.get("https://www.naukri.com/mnjuser/profile")
        # Find resume headline → toggle trailing period → save
        driver.quit()
```

---

## WHAT THE UPGRADED PIPELINE GIVES ME EVERY MORNING

```
DAILY OUTPUT (ready at 8 AM):

📋 TODAY'S APPLY LIST — all links ready in Google Sheet:
  ┌─────────────┬──────────────┬──────────────┬────────────┬────────────┬────────────────┐
  │ Company     │ Careers Page │ Wellfound    │ Naukri     │ Instahyre  │ LinkedIn       │
  │             │ (auto-applied│ (auto-applied│ (click→app)│ (click→app)│ (click→connect)│
  │             │  or CLICK)   │  or CLICK)   │            │            │                │
  ├─────────────┼──────────────┼──────────────┼────────────┼────────────┼────────────────┤
  │ Sarvam AI   │ ✅ AUTO      │ ✅ AUTO      │ —          │ —          │ ✅ 2 contacts  │
  │ DevRev      │ ✅ AUTO      │ ✅ AUTO      │ ✅ LINK    │ ✅ LINK    │ ✅ 2 contacts  │
  │ Murf AI     │ ✅ AUTO      │ ⚠️ MANUAL    │ ✅ LINK    │ —          │ ✅ 1 contact   │
  │ Company X   │ ❌ NOT FOUND │ —            │ ✅ LINK    │ ✅ LINK    │ ✅ 2 contacts  │
  └─────────────┴──────────────┴──────────────┴────────────┴────────────┴────────────────┘
  
  + 15-25 career portal links from JobCode18 scraper
  + Ready-to-paste LinkedIn connect notes for each contact

📋 EMAILS ALREADY SENT (automated overnight):
  ✓ Sent email to name@company.com at 8:02 AM
  ✓ Sent email to name@company.com at 8:07 AM
  ✓ Sent follow-up to name@company.com (Day 7, no response)
  ... (5-8 emails auto-sent)

📋 FOLLOW-UPS DUE:
  → Reply to Rahul (he responded yesterday)
  → Follow-up LinkedIn message to Priya (Day 7)

📋 NAUKRI PROFILE: ✅ Auto-updated at 7:55 AM
```

---

## COMBINED IMPACT

```
                        NOW              WITH ALL 8 UPGRADES    SAM
─────────────────────────────────────────────────────────────────────────────
Careers page apps/mo    0                18-24 (automated)       20-30
Wellfound apps/mo       0                15-20 (auto+manual)     30-40
Naukri apps/mo          0                15-20 (manual, links    40-50
                                                 in sheet)
Instahyre apps/mo       0                10-15 (manual, links)   10-15
JobCode18 apps/mo       5 (manual)       15-25 (scraper+auto)    0
LinkedIn outreach/mo    70               70 (semi-auto)          70
Email outreach/mo       20               50-60 (AUTO-SENT)       30
─────────────────────────────────────────────────────────────────────────────
TOTAL touchpoints/mo    95               193-234                  250
─────────────────────────────────────────────────────────────────────────────
ATS applications/mo     5                73-104                   140-150
Tech rounds/mo          1.5              5-7                      6
Offers/mo               0.27             1.0-1.3                  1.0
Manual hours/week       2 (search heavy) 2-3 (clicking only)     15-20
Time to first offer     Month 3-4        Month 1.5-2              Month 1.5-2
─────────────────────────────────────────────────────────────────────────────
```

**I match or beat Sam at 1/6th the manual time.**

---

## MY MANUAL WORK PER WEEK (after all upgrades)

```
Monday:    Pipeline + auto-apply ran overnight. Open sheet (2 min).
           Click Naukri/Instahyre links to apply (15 min).
           Semi-auto send 10 LinkedIn connects (15 min clicking Send).
           
Tuesday:   Check auto-apply results — any failed? Manually apply those (10 min).
           Semi-auto send 5 more connects (10 min).
           
Wednesday: Check follow-ups due (outreach_engine --followups). 
           Send follow-up LinkedIn messages (10 min).

Thursday:  Pipeline run 2 (automated). Review new leads (10 min).
           Click remaining Naukri/Instahyre links (10 min).

Friday:    Check replies. Schedule any calls. (10 min)

TOTAL: ~90 min/week = 1.5 hrs/week
```

---

## BUILD ORDER

### Week 1 (do this NOW — biggest impact)
- [ ] Build `auto_applier.py` — careers page auto-apply + Wellfound auto-apply (with fallback)
- [ ] Build `CareerPortalFinder` — find all platform links per company, add to Sheet
- [ ] Widen `TARGET_COMPANY_CRITERIA` in job_pipeline_v2.py (3 number changes)
- [ ] Fix `SeenCompaniesCache` TTL: 180 → 30 days (1 line change)
- [ ] Fix stale comments at lines 9, 1516, 3225

### Week 2
- [ ] Build `JobCode18Source` — scrape jobcode18 website for career portal links
- [ ] Add `InstahyreSource` class to job_pipeline_v2.py
- [ ] Add `NaukriSource` class to job_pipeline_v2.py
- [ ] Add all three to `_ALL_SOURCES` dict
- [ ] Build `NaukriProfileUpdater` — daily micro-edit

### Week 3
- [ ] Build `EmailEnricher` (Hunter.io + pattern guess + SMTP verify)
- [ ] Build `EmailSender` (auto-send via Gmail SMTP with delays)
- [ ] Build auto follow-up email sending (Day 7 + Day 14)
- [ ] Build semi-auto `LinkedInSender` in outreach_engine.py
- [ ] Add `--send` and `--auto-apply` CLI flags

---

## FILES

```
MODIFIED:
  job_pipeline_v2.py    → wider filters, cache fix, new sources (Instahyre, Naukri, 
                          JobCode18), CareerPortalFinder, EmailEnricher
  outreach_engine.py    → EmailSender, LinkedInSender, auto follow-ups, --send flag

NEW:
  auto_applier.py       → Careers page auto-apply + Wellfound auto-apply
  naukri_updater.py     → Daily Naukri profile micro-edit

DEPENDENCIES:
  → Hunter.io API key (free: 25/month, paid $49/mo: 500/month)
  → Everything else uses existing Brave API, Selenium, gspread
```

---

## WHAT'S AUTOMATED vs WHAT'S MANUAL

| Task | Status | Risk Level |
|---|---|---|
| Finding companies (6 sources + JobCode18) | ✅ Automated | Zero (API calls) |
| Finding ALL apply links (careers/WF/Naukri/IH) | ✅ Automated | Zero (Brave API) |
| Careers page auto-apply (Greenhouse/Lever) | ✅ Automated | Zero (decentralized) |
| Wellfound auto-apply | ✅ Automated | ⚠️ Low (Brave profile + delays, fallback to manual) |
| Finding emails (Hunter.io + pattern guess) | ✅ Automated | Zero (API) |
| Sending cold emails | ✅ Automated | Zero (your mailbox) |
| Sending follow-up emails (Day 7, 14) | ✅ Automated | Zero (your mailbox) |
| Naukri profile daily update | ✅ Automated | Zero (your profile, one edit) |
| CRM tracking | ✅ Automated | Zero (your Sheet) |
| **Clicking "Apply" on Naukri links** | ❌ Manual | — (CAPTCHAs) |
| **Clicking "Apply" on Instahyre links** | ❌ Manual | — (CAPTCHAs) |
| **Clicking "Send" on LinkedIn connects** | ❌ Manual | — (ban risk if automated) |
| **Responding to replies** | ❌ Manual | — (human judgment) |
| **Scheduling/taking interview calls** | ❌ Manual | — (obviously) |

**Pipeline automates: all discovery + careers auto-apply + email outreach + follow-ups.**
**I do manually: Naukri/Instahyre apply clicks + LinkedIn sends + interviews.**
**Time split: ~90 min/week manual. Everything else runs on its own.**

---

## THE HONEST COMPARISON

```
Sam (pure manual):          ~1.0 offers/month   | 15-20 hrs/week | often LinkedIn restricted
Old pipeline (no upgrades): ~0.27 offers/month   | 2 hrs/week     | no ban risk but low output
This plan (all 8 upgrades): ~1.0-1.3 offers/month | ~90 min/week   | zero ban risk on safe channels

Where this plan beats Sam:
  → Signal-aware outreach (founder-direct, not ATS-filtered)
  → Auto-sent emails with follow-ups (Sam forgets follow-ups)
  → Careers page auto-apply runs overnight (Sam spends hours clicking)
  → Pipeline finds companies BEFORE they post on LinkedIn

Where Sam still has an edge:
  → 150 Wellfound/Naukri/LinkedIn clicks = more raw ATS volume
  → But pipeline + manual Naukri/Instahyre clicks closes most of this gap

Bottom line: same output, 1/10th the time, accounts stay alive.
```
