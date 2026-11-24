# Referral-First Job Platform — Complete Build Plan
> "We don't send you to apply. We apply for you AND send you to the right person."

---

## WHAT WE ARE BUILDING

A platform where any job seeker inputs their profile and gets:
1. Matched jobs (from career portals + aggregators — NOT just LinkedIn)
2. Honest fit score per job (before they waste time applying)
3. Resume rewritten for that exact job
4. **Auto-apply through ATS** — the platform submits applications for you
5. The RIGHT person to contact at that company (warm signal)
6. A personalized outreach message — signal-aware
7. Follow-up automation if no reply
8. Full application tracker

**Core promise:** We do both — apply through ATS AND connect you to the decision-maker. No other platform does both.

### Why both matter (the math)
```
Apply-only (like Naukri/LinkedIn):   150 apps → 22 ATS passes → 12 calls → ~1 offer/month
Referral-only (like current pipeline): 70 outreach → 5 replies → 2 calls → ~0.27 offers/month
Both together:                        150 apps + 70 outreach → ~1.3 offers/month (better quality)

User does: inputs profile, clicks "Run". Platform does everything else.
Manual work: click Send on LinkedIn connects (~15 min/day) + take interview calls.
```

---

## ARCHITECTURE OVERVIEW

```
User Profile (skills, experience, target roles, location, college)
        ↓
[Module 1] Job Discovery Engine — 8 sources, career portals first
        ↓
[Module 2] Fit Scorer — honest match score per job
        ↓
[Module 3] Resume Tailor — rewrite resume for THIS specific JD
        ↓
[Module 4] Warm Contact Finder — who to contact + why they'll respond
        ↓
  ┌─────────────────┬──────────────────────┐
  │                 │                      │
[Module 5]      [Module 6]          Both run in parallel
Auto-Apply      Outreach Generator  for every matched job
(ATS submit)    (signal-aware msg)
  │                 │
  └────────┬────────┘
           ↓
[Module 7] Follow-Up Tracker — 7-day sequence automation
           ↓
[Module 8] Application CRM — track everything in one place
```

---

## MODULE 1 — JOB DISCOVERY ENGINE

### What it does
Finds jobs from multiple sources BEFORE they're everywhere. Career portals first.

### Sources (priority order)
1. **Company Career Portals** — direct scraping (highest signal, freshest jobs)
2. **Wellfound** — startups (already built in job_pipeline_v2.py)
3. **YC Jobs** — YC batch companies (already built)
4. **YourStory / Inc42** — Indian startup funding + hiring signals (already built)
5. **Instahyre** — India-specific, AI/ML heavy, founders post directly (NEW)
6. **Naukri** — volume jobs, India's largest job board (NEW)
7. **Indeed India** — broad coverage
8. **LinkedIn Jobs** — public listings only, no login (grey zone, use carefully)

### Career Portal Crawler (new — most important)
```
Input: list of target companies (user provides or we suggest)
Process:
  1. Find careers page URL (Google: "company name careers site:company.com")
  2. Scrape /careers or /jobs page
  3. Extract: role title, JD text, location, date posted
  4. Store in DB with company_id
Output: fresh jobs before they hit aggregators
```

### Key design decisions
- Cache all jobs in SQLite with `posted_date`
- Dedup across sources (same job on Wellfound + career portal = one entry)
- Flag jobs posted < 7 days as HIGH PRIORITY (hiring intent is fresh)
- Store full JD text — needed for resume tailoring in Module 3

---

## MODULE 2 — FIT SCORER

### What it does
Scores user profile vs job description HONESTLY before they apply.
Most platforms let you apply to everything. We tell you the truth.

### Scoring dimensions (0-10 each)
| Dimension | How scored |
|---|---|
| Skills match | LLM compares user skills vs JD requirements |
| Experience level | Years + seniority match |
| Domain match | Industry / sector alignment |
| Location fit | Remote / city match |
| Education match | Degree requirements |

### Overall score
- 8–10 → Strong match. Apply immediately.
- 5–7 → Possible. Resume tailoring can close the gap.
- Below 5 → Honest: "Not a strong fit. Here's what you'd need."

### Key design decision
**Never hide a low score.** Trust is built by honesty.
Show: "Your profile is 4/10 for this role. Missing: 2+ years Python, MLOps experience."
This is what no other platform does. This is your trust builder.

### Tech
```python
def score_fit(user_profile: dict, job_description: str) -> FitScore:
    prompt = f"""
    User profile: {user_profile}
    Job description: {job_description}
    
    Score fit 0-10 on: skills, experience, domain, location, education.
    Return JSON with scores + specific gaps.
    Be honest. Don't inflate scores.
    """
    return call_llm(prompt, response_format="json")
```

---

## MODULE 3 — RESUME TAILOR

### What it does
Rewrites user's resume for ONE specific job. Not generic improvement — targeted rewrite.

### Process
```
Input: user master resume + job JD + fit score gaps
Steps:
  1. Extract keywords from JD (skills, tools, phrases ATS looks for)
  2. Identify which user experiences map to JD requirements
  3. Rewrite bullet points to mirror JD language
  4. Add missing keywords where honestly applicable
  5. Flag gaps that can't be filled honestly (don't hallucinate experience)
Output: tailored resume + ATS keyword coverage score
```

### Key design decision
- Keep one MASTER resume in profile
- Generate tailored version per application — never overwrite master
- Show keyword coverage: "This resume now covers 14/18 keywords from JD"
- Never add experience the user doesn't have — flag gaps instead

### Resume formats
- Accept: PDF, DOCX
- Output: PDF (clean, ATS-safe format) + DOCX (editable)

---

## MODULE 4 — WARM CONTACT FINDER

### This is the core differentiator. Build this best.

### What it does
For every job, find the RIGHT person to contact — not just "someone at the company."

### What makes a contact "right"
Ranked by signal strength:
1. **Alumni match** — same college (IIT/NIT/college) as user → highest reply rate
2. **Hiring manager** — person who posted the job or manages the team
3. **Recruiter at company** — internal recruiter, not agency
4. **Engineer on team** — peer who can refer
5. **Founder/CTO** — for startups < 50 people

### How to find them (legal sources only)
```
Sources (in order):
1. Brave Search API — "engineer at [company] IIT" / "hiring manager [company] AI"
2. Company LinkedIn page (public, no login) — team members listed
3. Apollo.io API — has legal data agreements, good for emails
4. Hunter.io API — finds emails by company domain
5. GitHub — for engineering roles, find contributors from company
6. Twitter/X — founders often public and responsive
```

### Alumni detection (your secret weapon — expand from IITK)
```python
ALUMNI_NETWORKS = [
    "IIT Bombay", "IIT Delhi", "IIT Madras", "IIT Kharagpur",  # IITs
    "IITK", "IIT Roorkee", "IIT Hyderabad", "IIT Bangalore",
    "NIT Warangal", "NIT Trichy", "BITS Pilani",               # NITs/BITS
    # Add user's own college dynamically
]

def find_warm_contacts(company: str, user_college: str) -> list[Contact]:
    # First: search for alumni from user's college at this company
    # Then: search for hiring managers
    # Then: search for recruiters
    # Rank by warmth score
```

### Contact warmth score
```
+5 → same college as user
+4 → posted "we're hiring" in last 30 days
+3 → company raised funding in last 90 days
+3 → YC founder (expects to be contacted by engineers)
+2 → active on LinkedIn/Twitter (will see your message)
+1 → Indian name (cultural context match for Indian users)
```

### Output per contact
```json
{
  "name": "Rahul Sharma",
  "title": "Engineering Manager — ML",
  "company": "Sarvam AI",
  "college": "IIT Bombay",
  "warmth_score": 8,
  "why_they_will_respond": "Same college. Posted hiring tweet 5 days ago.",
  "contact_method": "LinkedIn DM",
  "linkedin_url": "...",
  "email": "name@company.com"  // via Hunter.io if available
}
```

---

## MODULE 5 — AUTO-APPLY ENGINE (NEW — THE MISSING PIECE)

### Why this module exists
```
Without auto-apply:  Platform finds jobs + contacts → user still has to manually apply everywhere
With auto-apply:     Platform finds jobs + contacts → platform ALSO submits applications for you

This is the difference between ~0.27 offers/month and ~1.3 offers/month.
No other referral platform does both. This is the edge.
```

### What it does
For every job with fit_score >= 6, automatically submit the user's tailored resume through the company's application system.

### How it works
```
For each matched job:
  1. If source = wellfound → navigate to listing → click Apply → fill form → submit
  2. If source = career_portal → find apply page → fill form → submit
  3. If source = instahyre/naukri → navigate to listing → apply through platform
  4. Log result in CRM: APPLIED / NO_FORM_FOUND / ALREADY_APPLIED
  5. Trigger Module 6 outreach in PARALLEL (apply + contact founder simultaneously)
```

### Form filling strategy
```
Standard fields (auto-fill from UserProfile):
  ✓ Name, email, phone, LinkedIn URL
  ✓ Upload tailored resume PDF (from Module 3)
  ✓ Cover letter (LLM-generated, job-specific)
  ✓ Years of experience, current company
  ✓ Location, work authorization

Non-standard fields:
  ✓ If text field: LLM generates answer based on JD + user profile
  ✓ If dropdown: match closest option to user data
  ✗ If CAPTCHA: flag for user to solve (rare on careers pages)
```

### Key design decisions
- Apply to ALL jobs with fit >= 6, not just the top ones (volume matters for ATS channel)
- Use tailored resume from Module 3, not master resume
- Never apply twice to the same job (dedup in SQLite)
- Log every application with timestamp for follow-up tracking
- Human-speed delays between applications (30-90 seconds) to avoid bot detection

---

## MODULE 6 — OUTREACH GENERATOR

### What it does
Writes the exact message to send — different for every signal combination.
Runs IN PARALLEL with Module 5 auto-apply — user gets both ATS application AND direct outreach.

### Signal matrix (already partially built in outreach_engine.py — extend it)

| Signal | Message type |
|---|---|
| Alumni contact | Lead with college connection first |
| Funded company | Reference the raise, show excitement for growth stage |
| YC company | Reference batch, show you know YC culture |
| Hiring manager | Direct ask — "I applied, would love your perspective" |
| Peer engineer | Ask for referral honestly, offer to share your work |
| Founder (<50 people) | Direct, brief, show you understand their problem |

### Message rules (non-negotiable)
- Under 100 words for LinkedIn DM
- Under 200 words for email
- Always one specific reason why you're reaching out (the hook)
- Always one clear ask (not vague "let's connect")
- Never attach resume in first message
- Always reference something specific (their post, company news, shared college)

### Follow-up sequence
```
Day 0: First message sent
Day 7: Follow-up if no reply — different angle, shorter
Day 14: Final follow-up — "closing the loop"
Day 21: Mark as cold, suggest different contact at same company
```

---

## MODULE 7 — FOLLOW-UP TRACKER

### What it does
Automates the follow-up schedule. 80% of callbacks come from follow-ups.

### States per application
```
DISCOVERED → SCORED → AUTO-APPLIED → CONTACTED → REPLIED → INTERVIEW → OFFER → REJECTED → GHOSTED
```

### Automation rules
```
If status = CONTACTED and days_since > 7 → trigger follow_up_1
If status = CONTACTED and days_since > 14 → trigger follow_up_2
If status = CONTACTED and days_since > 21 → mark GHOSTED, suggest new contact
If status = REPLIED → alert user immediately
```

### Daily briefing (already exists in outreach_engine.py — extend it)
```
Morning digest:
- 3 new high-fit jobs found (with fit scores)
- 4 auto-applications submitted overnight ← NEW
- 2 follow-ups due today (with draft messages)
- 1 reply received (!)
- 5 outreach messages ready to send
```

---

## MODULE 8 — APPLICATION CRM

### What it does
One place to see everything. No spreadsheet juggling.

### Data per application
```
Company name + logo
Role title + fit score
Resume version used (tailored by Module 3)
Auto-apply status (APPLIED / NO_FORM / PENDING) ← NEW
Contact found (name, title, warmth score)
Outreach sent (date, method, message)
Status + last action date
Notes
Next action due
```

### Storage
- SQLite locally (for privacy, no cloud required)
- Optional Google Sheets sync (already built in both files)

---

## DATA MODELS

```python
@dataclass
class UserProfile:
    name: str
    email: str
    phone: str
    college: str          # key for alumni matching
    skills: list[str]
    experience_years: int
    current_role: str
    target_roles: list[str]
    target_companies: list[str]
    target_locations: list[str]
    master_resume_path: str
    linkedin_url: str

@dataclass
class Job:
    id: str
    title: str
    company: str
    company_size: str       # startup / mid / enterprise
    source: str             # wellfound / career_portal / naukri / etc
    jd_text: str            # full JD — needed for tailoring
    posted_date: datetime
    location: str
    salary_range: str
    apply_url: str
    hiring_signal: str      # job_post / funding / yc_batch / launch
    fit_score: FitScore     # filled after scoring

@dataclass
class Contact:
    name: str
    title: str
    company: str
    college: str
    warmth_score: int
    why_respond: str
    linkedin_url: str
    email: str
    contact_method: str     # linkedin_dm / email / twitter

@dataclass
class Application:
    job: Job
    contact: Contact
    resume_version_path: str
    outreach_message: str
    status: str
    sent_date: datetime
    reply_received: bool
    follow_up_dates: list[datetime]
    notes: str
```

---

## TECH STACK

### Backend (Python)
```
job_pipeline_v2.py     → already built, extend with career portal crawler + Instahyre + Naukri
outreach_engine.py     → already built, extend signal matrix + semi-auto LinkedIn sender
auto_applier.py        → NEW (the missing piece — ATS submission engine)
fit_scorer.py          → new
resume_tailor.py       → new
contact_finder.py      → new (extends IITKAlumniSource to all colleges)
crm.py                 → extend existing CRM writer
```

### LLM
```
Anthropic Claude API (claude-sonnet-4-20250514)
  - Fit scoring
  - Resume tailoring
  - Outreach generation
  - JD keyword extraction
```

### APIs needed
```
Brave Search API        → already have (contact finding, company research)
Anthropic API           → LLM calls
Hunter.io API           → email finder (free tier: 25/month)
Apollo.io API           → contact enrichment (free tier available)
Google Sheets API       → CRM sync (already built)
```

### Frontend (Phase 2)
```
Streamlit — fastest to build, wire directly to existing Python
OR
React + FastAPI — if you want proper web app
```

### Database
```
SQLite (already used for cache + dedup)
  Tables:
  - jobs
  - contacts
  - applications
  - user_profile
  - seen_companies (already exists)
  - query_cache (already exists)
```

---

## BUILD ORDER

### Week 1 — Auto-Apply + Discovery (biggest impact first)
- [ ] Build auto_applier.py (Wellfound apply + careers page apply)
- [ ] Add career portal crawler (find /careers pages, scrape JDs)
- [ ] Add InstahyreSource + NaukriSource to job_pipeline_v2.py
- [ ] Widen company filters (employee 5-200, add Series B, founded 2018+)
- [ ] Fix SeenCompaniesCache TTL (180 days → 30 days)
- [ ] Store full JD text in jobs table

### Week 2 — Intelligence layer
- [ ] Build fit_scorer.py (LLM-based, returns JSON scores + gaps)
- [ ] Build resume_tailor.py (keyword extraction + targeted rewrite)
- [ ] Wire auto-apply to only apply when fit_score >= 6

### Week 3 — Contact finder + outreach
- [ ] Build contact_finder.py (Brave + Apollo + Hunter integration)
- [ ] Extend alumni finder from IITK → all IITs + NITs + BITS
- [ ] Add contact warmth scoring
- [ ] Expand outreach templates for all signal types
- [ ] Build follow-up sequence automation

### Week 4 — CRM + UI
- [ ] Build application CRM (extend existing CRM writer)
- [ ] Build daily briefing with auto-apply status
- [ ] Build Streamlit dashboard to tie everything together

---

## WHAT IS GENUINELY UNIQUE ABOUT THIS

1. **Auto-apply + referral together** — applies AND connects you to the right person (nobody does both)
2. **Honest fit score** — tells you when NOT to apply (nobody does this)
3. **Alumni warmth graph** — IIT/NIT match = 5x reply rate
4. **Signal-aware outreach** — funded startup ≠ bootstrapped startup message
5. **Career portal first** — jobs before they hit aggregators
6. **Full follow-up automation** — the step most people skip
7. **~75 min/week manual work** — everything else is automated

---

## WHAT YOU CANNOT CLAIM (be honest)

- ❌ "Guaranteed interview in 30 days" — too many factors outside your control
- ❌ "We'll get you a job" — placement agencies say this, it backfires
- ✅ "We apply for you AND connect you to the decision-maker"
- ✅ "We find the right person, not just the right job"
- ✅ "We tell you honestly if you're not a fit — before you waste time"
- ✅ "~1.3 offers/month with 75 min/week of your time"

---

## LEGAL NOTES

| What we do | Legal status |
|---|---|
| Scrape public career portals | ✅ Safe |
| Scrape public Wellfound/YC | ✅ Safe |
| Auto-apply through public career forms | ✅ Safe (same as human filling a form) |
| Brave Search API for contacts | ✅ Safe (API ToS compliant) |
| Hunter.io / Apollo.io for emails | ✅ Safe (they have data agreements) |
| LinkedIn public page scraping | ⚠️ Grey — use minimally, no login |
| LinkedIn semi-auto sending | ⚠️ Grey — human clicks final Send button |
| LinkedIn full automation | ❌ Avoid completely |
| Store resumes | ✅ Safe with user consent |
| AI rewrite of user's own resume | ✅ Completely safe |

---

## FILES TO CREATE (from scratch)

```
project/
├── job_pipeline_v2.py          ← already built (extend: Instahyre, Naukri, wider filters, cache fix)
├── outreach_engine.py          ← already built (extend: semi-auto LinkedIn sender)
├── auto_applier.py             ← NEW (ATS submission engine — Week 1 priority)
├── fit_scorer.py               ← NEW
├── resume_tailor.py            ← NEW
├── contact_finder.py           ← NEW (extends IITK alumni to all colleges)
├── career_portal_crawler.py    ← NEW
├── crm.py                      ← NEW (extend existing logic)
├── app.py                      ← NEW (Streamlit UI)
├── pipeline_cache.db           ← already exists
├── .env                        ← already exists
└── requirements.txt            ← update
```

---

## PASTE THIS INTO PROJECT CLAUDE TO START

> "I am building a referral-first job platform. Here is the full plan [paste this doc]. I have two existing files: job_pipeline_v2.py (startup discovery + scoring + Google Sheets) and outreach_engine.py (prioritizer + message composer + CRM writer + follow-up tracker). Start by building fit_scorer.py — it takes a user profile dict and a job description string, calls Claude API, and returns a FitScore with scores 0-10 on skills/experience/domain/location/education plus specific gaps. Return JSON. Be honest, never inflate scores."

Then build one module at a time.
