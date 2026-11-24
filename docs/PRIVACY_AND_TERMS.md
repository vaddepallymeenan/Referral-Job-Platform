# Privacy Policy & Terms of Service
**Last Updated: May 31, 2026**

This document sets forth the Privacy Policy and Terms of Service for the **Honest Job Intelligence SaaS Platform** (the "Platform"). The Platform is designed and maintained in strict compliance with the **Indian Digital Personal Data Protection (DPDP) Act (2023)** and the **General Data Protection Regulation (GDPR) (EU 2016/679)**.

---

## Part 1: Privacy Policy

We are committed to the security and privacy of technical candidates. Unlike traditional hiring platforms, we do **not** sell, rent, or trade candidate PII. 

### 1. Data Collected & Purpose Specification
We collect and process personal data solely to perform automated candidate-to-job matching, gap analysis, and tailored outreach recommendations:
*   **Candidate Email Address:** Used as your primary account identifier and authentication anchor.
*   **Resume PDF Content:** We extract raw resume text to structure your technical profile (skills, educational credentials, work histories).
*   **Structured Technical Profile:** Synthesized skills and target roles used exclusively for ranking vector similarity.
*   **Kanban Application Status:** Board positions (Prioritized, Applied, Interviewing, Complete) tracked to build empirical placement metrics.

### 2. Legal Basis for Processing
*   **GDPR (Article 6.1.a):** Processing is based on explicit candidate consent, given freely when uploading a resume PDF.
*   **DPDP Act (2023) (Section 6):** Processing is anchored on the candidate’s unequivocal consent given for the specific, specified purpose of finding technical employment.

### 3. Data Protection & Security Architecture (PII at Rest)
To protect your highly sensitive work histories and contact data from database breaches, we employ a state-of-the-art **Field-Level Cryptographic Security Architecture**:
*   **Symmetric AES-GCM (Fernet) Encryption:** Every resume’s raw text is symmetrically encrypted using a secure base64 AES-256 token immediately upon receipt.
*   **Zero Cleartext Resumes:** The raw text column in our physical database holds strictly encrypted cipher block bytes. It can only be read when decrypted in memory during active candidate matching requests.
*   **PGVector Dimensions Security:** High-dimensional embeddings (768 dimensions) are mathematically secure and cannot be reversed by third parties to reconstruct your plain text resume.

### 4. Principal / Data Subject Rights
In accordance with GDPR Chapter III and DPDP Act Section 11, candidates hold the following rights:
*   **Right to Access:** You can fetch your structured candidate profile dynamically from your dashboard at any time.
*   **Right to Erasure / "Right to be Forgotten":** You may purge your entire account, uploaded resume, and application tracking history instantly.
*   **Right to Withdraw Consent:** You can withdraw your consent for profile matching at any time by deleting your uploaded file.

### 5. Third-Party Data Handlers & LLMs
To structure profiles and generate signal-aware connection notes, we transmit resume text and job descriptions to **Google Gemini APIs** under enterprise-grade data privacy schemas:
*   **Zero LLM Training:** Your resume contents are transmitted via standard APIs which explicitly forbid the use of customer payloads for foundation model training or optimization.

---

## Part 2: Terms of Service

By registering an account or uploading a resume, you agree to these legally binding terms:

### 1. Acceptable Use & Zero-Tolerance Abuse Zones
To maintain platform integrity and protect candidates from platform-level account bans on third-party networks:
*   **NO Automated Form-Filling / Auto-Appliers:** You may not connect browser automation agents (Selenium, Playwright, Puppeteer) to auto-fill Greenhouse, Lever, or Ashby job applications via our platform data.
*   **NO Automated Outreach / Spam:** Programs or extensions executing automated cold outreach or mass messaging are strictly prohibited. Connection notes are designed to be sent **manually by the human-in-the-loop** to prevent platform bans.

### 2. Limitation of Liability
The Platform calculates matching scores and advice based on unauthenticated, public ATS listings. We make no guarantees regarding:
*   The accuracy of third-party public Greenhouse/Lever postings.
*   Whether a high match score will result in a phone screen or placement.
*   Platform downtime during routine ATS API scraper migrations.

### 3. Subscription Tiers & Billing
*   **Free Tier:** Free users are entitled to standard resume parsing, top 10 curation matching, and basic application tracking.
*   **Payment & Refunds:** Paid tiers (Sprint plans) are charged in advance. Cancellations take effect at the end of the active billing cycle.

### 4. Governing Law & Dispute Resolution
*   **Beta Stage:** This software is in a beta stage. Standard dispute resolution is handled via mutual arbitration under the Arbitration and Conciliation Act (India) or local European arbitration bodies as applicable to the user's domicile.
