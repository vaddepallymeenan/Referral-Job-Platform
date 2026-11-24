import requests
import sys
import os

def test_saas_billing_monetization():
    print("━" * 75)
    print("  🚀  TESTING MONTH 6: SAAS PAYWALL TRANSITIONS & STRIPE BILLING")
    print("━" * 75)
    
    API_URL = "http://localhost:8000"
    EMAIL = "billing.test@example.com"
    RESUME_PATH = "resume.pdf"
    
    # 0. Register/Get Test User (Defaults to Free Tier)
    print("\n  [0] Initializing test user profiles in DB...")
    try:
        user_res = requests.post(f"{API_URL}/api/users", json={"email": EMAIL}, timeout=15)
        if user_res.status_code not in [200, 201]:
            print(f"  ✗ User initialization failed: {user_res.text}")
            sys.exit(1)
        user = user_res.json()
        print(f"  ✓ User registered! Account: {user['email']} (Tier: {user['subscription_tier'].upper()})")
        
        # Reset user back to Free tier for clean test state
        requests.post(f"{API_URL}/api/billing/checkout", json={"email": EMAIL, "tier": "free"}, timeout=15)
    except Exception as e:
        print(f"  ✗ Backend connection failed: {e}")
        sys.exit(1)

    # Upload resume PDF stream so user has parsed experience records
    print("      - Seeding test candidate resume PDF...")
    try:
        with open(RESUME_PATH, "rb") as f:
            files = {"file": (os.path.basename(RESUME_PATH), f, "application/pdf")}
            upload_res = requests.post(
                f"{API_URL}/api/resume/upload",
                params={"email": EMAIL},
                files=files,
                timeout=20
            )
        assert upload_res.status_code == 200, f"Resume upload failed: {upload_res.text}"
        print("      ✓ Candidate resume parsed and indexed successfully!")
    except Exception as e:
        print(f"  ✗ Seeding failed: {e}")
        sys.exit(1)

    # Force sync mock jobs to ensure db has listings
    requests.post(f"{API_URL}/api/jobs/sync?force_mock=true", timeout=15)
    
    # Query raw jobs directly
    jobs_res = requests.get(f"{API_URL}/api/jobs", timeout=15)
    jobs = jobs_res.json()
        
    if not jobs:
        print("  ✗ No job listings available to run tests.")
        sys.exit(1)
        
    job_ids = [j["id"] for j in jobs]
    print(f"  ✓ Available target jobs for testing: {len(job_ids)}")

    # Reset outreach count in db to ensure clean testing counters
    import sqlite3
    conn = sqlite3.connect('job_platform.db')
    conn.cursor().execute('UPDATE users SET outreach_count = 0 WHERE email = ?', (EMAIL,))
    conn.commit()
    conn.close()

    # 1. Test Executive Tier locks on Free Plan
    print("\n  [1] Validating Executive-exclusive locks (Tailoring & Prep) on Free Tier...")
    
    # Target: Resume Tailoring
    tailor_res = requests.post(f"{API_URL}/api/resume/tailor", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Resume Tailoring Request: Code {tailor_res.status_code}")
    assert tailor_res.status_code == 402, f"Expected 402, got {tailor_res.status_code}"
    print("        ✓ Blocked successfully under 402 Payment Required!")
    
    # Target: Interview Prep
    prep_res = requests.post(f"{API_URL}/api/interview/prep", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Interview Prep Request: Code {prep_res.status_code}")
    assert prep_res.status_code == 402, f"Expected 402, got {prep_res.status_code}"
    print("        ✓ Blocked successfully under 402 Payment Required!")

    # 2. Test Saved Search Profile lock on Free Plan
    print("\n  [2] Validating Saved Search soft locks on Free Tier...")
    search_res = requests.post(f"{API_URL}/api/search_profile", params={"email": EMAIL}, json={
        "is_remote": True, "location": "US", "company_stage": "Series A", "keywords": "Python"
    }, timeout=15)
    print(f"      - Save Preferences Request: Code {search_res.status_code}")
    assert search_res.status_code == 402, f"Expected 402, got {search_res.status_code}"
    print("        ✓ Blocked successfully under 402 Payment Required!")

    # 3. Test 2-Outreach Draft Limit on Free Plan
    print("\n  [3] Validating 2 outreach notes cap on Free Tier...")
    # First Draft
    o1 = requests.post(f"{API_URL}/api/outreach/generate", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Outreach Draft 1: Code {o1.status_code}")
    assert o1.status_code == 200, f"Expected 200, got {o1.status_code}"
    
    # Second Draft
    o2 = requests.post(f"{API_URL}/api/outreach/generate", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Outreach Draft 2: Code {o2.status_code}")
    assert o2.status_code == 200, f"Expected 200, got {o2.status_code}"
    
    # Third Draft (Should be locked!)
    o3 = requests.post(f"{API_URL}/api/outreach/generate", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Outreach Draft 3: Code {o3.status_code}")
    assert o3.status_code == 402, f"Expected 402, got {o3.status_code}"
    print("        ✓ Blocked successfully under 402 Payment Required!")

    # 4. Trigger simulated Stripe Checkout to upgrade to EXECUTIVE
    print("\n  [4] Simulating Stripe Checkout upgrade to Executive Tier...")
    checkout_res = requests.post(f"{API_URL}/api/billing/checkout", json={"email": EMAIL, "tier": "executive"}, timeout=15)
    assert checkout_res.status_code == 200, f"Checkout failed: {checkout_res.text}"
    checkout = checkout_res.json()
    print(f"      - Upgrade status: {checkout['status'].upper()}")
    print(f"      - Active Plan: {checkout['tier'].upper()}")
    print(f"      - Stripe Checkout URL: {checkout['session_url']}")
    
    # 5. Verify Executive tier unlocks all locked features
    print("\n  [5] Validating Executive Tier unlocks...")
    
    # Test tailors
    tailor_unlock = requests.post(f"{API_URL}/api/resume/tailor", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Tailoring unlock check: Code {tailor_unlock.status_code}")
    assert tailor_unlock.status_code == 200, f"Expected 200, got {tailor_unlock.status_code}"
    print("        ✓ Resume tailoring is fully unlocked!")
    
    # Test interview prep
    prep_unlock = requests.post(f"{API_URL}/api/interview/prep", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Interview Prep unlock check: Code {prep_unlock.status_code}")
    assert prep_unlock.status_code == 200, f"Expected 200, got {prep_unlock.status_code}"
    print("        ✓ Interview Prep guide is fully unlocked!")
    
    # Test search preference setting
    search_unlock = requests.post(f"{API_URL}/api/search_profile", params={"email": EMAIL}, json={
        "is_remote": True, "location": "US", "company_stage": "Series A", "keywords": "Python"
    }, timeout=15)
    print(f"      - Save Preferences unlock check: Code {search_unlock.status_code}")
    assert search_unlock.status_code == 200, f"Expected 200, got {search_unlock.status_code}"
    print("        ✓ Saved Search Profiles are fully unlocked!")

    # Test unlimited outreach note drafts
    o_unlock = requests.post(f"{API_URL}/api/outreach/generate", json={"email": EMAIL, "job_id": job_ids[0]}, timeout=15)
    print(f"      - Outreach Draft 3 (Post-Upgrade): Code {o_unlock.status_code}")
    assert o_unlock.status_code == 200, f"Expected 200, got {o_unlock.status_code}"
    print("        ✓ Unlimited outreach note drafts are fully unlocked!")

    # Reset tier for final cleanup
    requests.post(f"{API_URL}/api/billing/checkout", json={"email": EMAIL, "tier": "free"}, timeout=15)
    
    print("\n  [6] Monetization and Paywall engine verification passed successfully!")
    print("  ✓ All tiers and access controls conform exactly to specifications.")
    print("━" * 75)

if __name__ == "__main__":
    test_saas_billing_monetization()
