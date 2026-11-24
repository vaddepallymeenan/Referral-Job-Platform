# SaaS Roadmap: Honest Job Intelligence Platform

This roadmap maps the transformation of our local Python pipeline automation into a highly focused, solo-founder-optimized, legally safe, and defensible SaaS product. It implements a strict discipline of **high leverage, low maintenance, and high user-value** based on the brutal realities of operating a solo startup.

---

## Table of Contents
1. [Product Philosophy & Scope](#1-product-philosophy--scope)
2. [Data Acquisition & Ingestion Strategy](#2-data-acquisition--ingestion-strategy)
3. [Technical Architecture Specification](#3-technical-architecture-specification)
4. [Phase-by-Phase MVP Roadmap (12 Months)](#4-phase-by-phase-mvp-roadmap-12-months)
5. [Moat Analysis & Defensibility Flywheel](#5-moat-analysis--defensibility-flywheel)
6. [Risk Management & Reality Check Checklist](#6-risk-management--reality-check-checklist)
7. [Validation & Go-To-Market Blueprint](#7-validation--go-to-market-blueprint)

---

## 1. Product Philosophy & Scope

### 🚫 Features We Will NEVER Build (Zero-Tolerance Zone)
*   **LinkedIn Integration / Automation:** Programmatic scraping, contact discovery, automated connection requests, or auto-messaging. High legal exposure, instant ban risk, and permanent maintenance cost.
*   **ATS Form Auto-Filling / Auto-Apply:** No Selenium/Playwright bots attempting to fill Greenhouse, Lever, or Workable forms. The selector rot and CAPTCHA handling is a full-time engineering sink. Let products like Simplify handle form-filling; our platform focuses on **prioritization and matching**.
*   **Mass Email Outreach / Scraping:** No programmatic cold emailing or scraping corporate contact emails. Avoids deliverability damage, SPF/DKIM engineering pain, and DPDP/GDPR compliance risks.
*   **Generic Open-Ended Chat / "AI Coach":** Open-ended conversational UI is a distraction. Users want concrete, structured, and fast answers.
*   **In-App Resume Builder:** Avoid competing directly with Canva, Teal, or Rezi. We will accept uploaded resumes and tailor them, not host or design them.
*   **Real-Time Job Syncing:** Real-time job polling is prohibitively expensive. Batch ingestion (once daily) is more than sufficient.

### ✅ Features We Will Build (The Focus Area)
*   **Standardized Resume Parser:** Single PDF upload structured into typed JSON (skills, experience, targets) via a fast, cheap LLM.
*   **Daily Public JSON ATS Ingest:** Clean, structured job extraction via unauthenticated endpoints (Greenhouse, Lever, Ashby, YC).
*   **Brutally Honest Fit Scoring:** Replaces empty praise with quantitative match scoring and explicit gap analysis (keywords, credentials, years of experience).
*   **The Weekly "Top 5" Prioritized Queue:** Curation over floodgates. An algorithm that highlights the 5 absolute best matches for a candidate each week.
*   **Contextual Outreach Drafts:** Generating tailored LinkedIn connection notes and cold messages that reference specific company events (funding, launches) that users send **manually**.
*   **Basic Application Kanban:** Simple tracking board (Applied, Interview, Offer, Rejected) to collect outcome data.

---

## 2. Data Acquisition & Ingestion Strategy

We will bypass brittle browser automation and use stable, versioned, public JSON endpoints. 

| Source | Target / Endpoint Pattern | Difficulty | Maintenance | Ingestion Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Greenhouse** | `https://boards-api.greenhouse.io/v1/boards/{company}/jobs` | Very Low | Low | Fetch public JSON payload. Covers ~30,000 tech companies. |
| **Lever** | `https://api.lever.co/v0/postings/{company}?mode=json` | Very Low | Low | Clean JSON payload. Covers massive startup footprint. |
| **Ashby** | `https://jobs.ashbyhq.com/{company}` GraphQL endpoints | Low-Medium | Medium | Growing rapidly. Map GraphQL query to Ashby schema. |
| **Workable** | `https://apply.workable.com/api/v3/accounts/{company}/jobs` | Medium | Medium | Fetch JSON from company Workable subdomains. |
| **YC Jobs** | Algolia Public Search API | Low | Low | Direct API queries against YC Algolia app keys. Excellent signal. |
| **Remotive** | `https://remotive.com/api/remote-jobs` | Very Low | Low | Free, stable JSON API for supplementary remote roles. |
| **Wellfound** | AngelList | High | Extremely High | **Avoid.** Scrape manually or pull only quarterly as a backup. |
| **Indeed / LinkedIn / Naukri** | Scraped listings | Extremely High | High | **Banned.** Scraping these invites aggressive IP blocking and legal risk. |

---

## 3. Technical Architecture Specification

Optimize for the "2:00 AM Solo-Engineer Rule." A unified relational database, server-side rendering, and a single server backend.

```
       [ Client Browser ]
               │
               ▼
   [ Next.js 14 / Tailwind / shadcn/ui ] (Vercel)
               │
               ▼
   [ FastAPI Monolith / Python ] (Railway / Render)
               │
      ┌────────┴────────┐
      ▼                 ▼
[ Supabase Postgres ] [ pgvector ]
```

### Database Schema Draft (Supabase / Postgres)
```sql
-- Enable Vector Extensions
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    subscription_tier TEXT DEFAULT 'free'
);

-- 2. Resumes
CREATE TABLE resumes (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    structured_json JSONB NOT NULL,
    embedding VECTOR(1536), -- text-embedding-3-small
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    PRIMARY KEY (user_id)
);

-- 3. Jobs
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL, -- 'greenhouse', 'lever', etc.
    ats_type TEXT NOT NULL,
    posted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    embedding VECTOR(1536) -- text-embedding-3-small
);

-- 4. Fit Scores (With Brutally Honest Gaps)
CREATE TABLE fit_scores (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    score INT CHECK (score BETWEEN 0 AND 100),
    gaps_json JSONB NOT NULL, -- missing skills, experience shortfalls
    scored_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    model_version TEXT NOT NULL,
    PRIMARY KEY (user_id, job_id)
);

-- 5. Applications (Kanban & Outcome tracking)
CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('prioritized', 'applied', 'interviewing', 'rejected', 'offer')),
    applied_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);
```

### Ingestion & Search Engine
*   **Daily Batch Ingestion:** A single scheduled GitHub Action or Railway cron runner that pulls from a managed list of 500 company ATS targets.
*   **Similarity Search:** Cosine similarity via `pgvector` computes the top matches.
    ```sql
    -- Semantic Search Query inside pgvector
    SELECT id, title, company, (embedding <=> :user_resume_embedding) AS distance
    FROM jobs
    WHERE is_active = TRUE
    ORDER BY distance ASC
    LIMIT 20;
    ```
*   **Deterministic Fallback:** Combine semantic distance with standard `tsvector` keyword indices for target fields like locations, roles, and technical terms.

---

## 4. Phase-by-Phase MVP Roadmap (12 Months)

### 🗓️ Weeks 1–4: Core Matching & Database Loop
- [x] Set up Next.js 14 repository on Vercel and a FastAPI backend on Railway.
- [x] Connect a free-tier Supabase PostgreSQL instance and initialize the schema.
- [x] Write a static JSON importer for Greenhouse and Lever APIs based on a curated list of 500 tech companies.
- [x] Build a local Python CLI script utilizing `pypdf` to parse a candidate's resume PDF into raw text.
- [x] Write the structured resume extraction LLM function (using `gpt-4o-mini` or `claude-3-5-haiku`) to output JSON.
- [x] Implement `pgvector` distance computation between resume embeddings and job postings.
- [x] **Milestone Check:** Verify you can upload a PDF and instantly print out the top 10 matching database jobs from Greenhouse/Lever.

### 🗓️ Weeks 5–8: The Honest Scorer & UI Launch
- [x] Code the `fit_scorer` API endpoint in FastAPI that returns:
    - [x] A strict, uninflated percentage score (0-100).
    - [x] A list of missing technical skills/keywords.
    - [x] Actionable resume optimization advice (e.g., "Add your experience with Kubernetes to bullet point 3").
- [x] Build the Next.js Web UI showing the prioritized job board.
- [x] Build a simple structured Outreach Note Generator page that takes a job description and spits out:
    - [x] An executive summary of the target company.
    - [x] A tailored, signal-aware 300-character LinkedIn connection note.
- [x] Deploy a simple Kanban board for job tracking (Prioritized → Applied → Interviewing → Complete).
- [x] **Milestone Check:** Fully close the loop: Resume Upload → Brutal Fit Score Card → LinkedIn Note Draft → Click "Applied".

### 🗓️ Weeks 9–12: Validation, Churn Analysis & Security
- [x] Add standard user authentication (Supabase Auth).
- [x] Set up database encryption at rest for raw resume texts and personal user data (PII).
- [x] Draft a clear, compliance-ready Privacy Policy and Terms of Service (DPDP Act & GDPR compliance).
- [x] Manually onboard 20-30 beta users. Do **not** charge yet, and do **not** run ads.
- [x] Track Week 1 and Month 1 user retention. Analyze if they come back to check new daily jobs.
- [x] **Milestone Check:** 10 core users actively utilizing the platform weekly for 4 consecutive weeks.

### 🗓️ Month 4: The Retention Engine (Weekly Digest)
- [x] Implement the **Monday Morning Digest Email** engine (SendGrid or Postmark):
    - [x] Automate a cron job that scores newly ingested jobs over the week.
    - [x] Compile the 5 highest-scoring, active roles.
    - [x] Email a clean, curated summary directly to the user.
- [x] Build Saved Search Profiles (so users can specify criteria like Remote vs India, Series A vs Growth).
- [x] Implement a cached AI Company Signal parser that records:
    - [x] Funding announcements (e.g. YourStory, Inc42).
    - [x] Product launches on ProductHunt.
    - [x] Signal weight is added to job prioritize algorithms.

### 🗓️ Month 5: Dynamic Resume Tailoring & Interview Prep
- [x] Build a highly intelligent Resume Tailoring API (utilizing `claude-3-5-sonnet`) to suggest context-aware rewrites of resume bullet points to address the identified gaps for a specific target job.
- [x] Implement an automated **Interview Prep Generator** that outputs:
    - [x] 10 highly probable technical and behavioral questions based on the job requirements.
    - [x] Suggested frameworks and talking points referencing the user's specific resume achievements.

### 🗓️ Month 6: The Paywall Transition & Monetization
- [x] Integrate Stripe billing.
- [x] Lock the system behind a simple, clear tier plan:
    - [x] **Free Tier:** 5 fit scores and 2 outreach drafts per month.
    - [x] **Premium Tier ($19/mo):** Unlimited fit scoring, outreach drafts, saved search alerts, and weekly digest.
    - [x] **Executive Tier ($49/mo):** Advanced resume tailoring, interview prep questions, and priority target list requests.
- [x] Achieve cash-flow positivity by converting at least 10 active beta testers to paying customers.


### 🗓️ Months 7–12: Building the Moat & Flywheel
- [x] **The Feedback Flywheel:** Track actual hiring outcomes reported by candidates. If a candidate got rejected at the phone screen for a 9/10 scored job, decrease weight on that matching model version.
- [x] **Direct Company Intelligence:** Parse tracking data to map ATS dynamics (e.g. "Greenhouse link closed within 48 hours = High Urgency", "Job open for 90 days with no hires = Stale").
- [x] Scale company ingestion pool from 500 to 5,000+ tech companies programmatically.

---

## 5. Moat Analysis & Defensibility Flywheel

We cannot outspend Jobright AI ($10M+ funding) or match the form-filling speed of Simplify. Instead, we compete on **depth, honesty, and local edge**.

```
   [ Honest Scoring / Gaps ] ───► [ High User Trust ]
               ▲                         │
               │                         ▼
     [ Model Adjusts ] ◄─── [ Outcome Tracking (Interview / Hire) ]
```

### The Four Pillars of Our Moat
1.  **The Outcome Feedback Flywheel:** Competitors use static keyword scoring. By forcing a clean feedback loop ("Did you get a phone screen?"), our matching algorithm trains on empirical placement data. After 1,000 recorded outcomes, our fit-scorer becomes objectively more predictive than standard models.
2.  **Brutally Honest Curation:** While Jobright or LinkedIn wants high engagement (inflating scores so users submit more resumes), we serve the candidate. A candidate who knows a job is a 3/10 will save 45 minutes and trust us forever when they avoid a silent rejection.
3.  **India-Specific Signal Edge:** None of the US-focused job aggregators properly parse Indian tech signals (YC India batches, YourStory/Inc42 funding rounds, IIT/BITS alumni networks, Keka/Zoho ATS boards). We hold a geographic moat for tech talent looking at Indian startups.
4.  **Weekly Email Curation Habit:** An elegant digest email on Monday morning bypasses standard "app fatigue". We become a weekly habit, not a browser utility.

---

## 6. Risk Management & Reality Check Checklist

Keep this checklist visible at all stages of development.

- [ ] **Greenhouse/Lever schema changes:** If they update their public APIs, does our ingestion fail silently?
    - *Mitigation:* Set up automated Sentry alerts on zero-results parsed from ingestion runs.
- [ ] **Semantic search irrelevance:** Does pgvector matching match unrelated roles due to poor embedding alignment?
    - *Mitigation:* Always post-filter semantic vector returns against strict SQL matches (e.g., must match at least one core tech skill in a deterministic array).
- [ ] **API Cost Spikes:** If a user uploads 100 resumes, will our LLM costs explode?
    - *Mitigation:* Implement strict rate-limiting on resume parsing and fit scoring (e.g., max 10 scores per day for free users).
- [ ] **Indian DPDP Act (2023) Compliance:** Storing PII (Resumes) without consent is illegal.
    - *Mitigation:* Ensure explicit user consent checkboxes on PDF uploads, strict database column-level encryption for resumes, and an automated "Delete My Account & Data" flow.
- [ ] **The Leaky Bucket Churn:** Users leave when they get a job. Churn will naturally be high.
    - *Mitigation:* Shift premium pricing to a one-time "Job Search Sprint" model ($49 flat for 3 months) or build downstream features ("Career Tracker").

---

## 7. Validation & Go-To-Market Blueprint

**Do not write a line of Next.js code until Month 1 validation is complete.**

### Phase 1 Validation (First 30 Days)
1.  Identify 30 active technical job seekers (AI engineers, Fullstack developers, Data Scientists).
2.  Conduct manual interviews. Ask exactly: *"Walk me through the last time you applied to a job. Where did you spend the most manual time?"*
3.  Do **not** pitch your product. Just listen. If 70% of them complain about **curation** ("I don't know what roles are actually active or realistic for me"), you have greenlighted the **Prioritization Scorer**.

### Phase 2 MVP Validation (Day 31-60)
1.  Instead of a complex UI, send a personalized, manual PDF report to 10 of your interviewees.
2.  Include: "5 jobs that fit you perfectly this week, 3 specific skills you are missing on your resume for these roles, and a tailored LinkedIn draft."
3.  If they ask, *"Can you send me this next Monday too?"*, you have validated the core loop.

### Phase 3 Pricing Test (Day 61-90)
1.  Ask those 10 users: *"I'm automating this pipeline. It will cost $10/month. Would you put your credit card in now to reserve a spot?"*
2.  If 3 out of 10 users pay before the software is finished, you have validated the market. **Now, go build the software.**
