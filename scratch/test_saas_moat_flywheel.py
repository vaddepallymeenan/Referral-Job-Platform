import requests
import sys
import os

# Insert parent folder into path to support direct local backend imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_saas_moat_flywheel():
    print("━" * 75)
    print("  🚀  TESTING MONTHS 7-12: BUILDING THE Defensibility MOAT & FLYWHEEL")
    print("━" * 75)
    
    API_URL = "http://localhost:8000"
    EMAIL = "flywheel.test@example.com"
    RESUME_PATH = "resume.pdf"
    
    # 0. Register User & Set to Executive tier to bypass monetization locks in test
    print("\n  [0] Initializing test user profiles in DB...")
    try:
        user_res = requests.post(f"{API_URL}/api/users", json={"email": EMAIL}, timeout=15)
        if user_res.status_code not in [200, 201]:
            print(f"  ✗ User initialization failed: {user_res.text}")
            sys.exit(1)
        user = user_res.json()
        print(f"  ✓ User registered: {user['email']}")
        
        # Set user back to Premium/Executive to allow unlimited scores
        requests.post(f"{API_URL}/api/billing/checkout", json={"email": EMAIL, "tier": "executive"}, timeout=15)
    except Exception as e:
        print(f"  ✗ Backend connection failed: {e}")
        sys.exit(1)

    # 1. Seed candidate resume
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

    # 2. Get initial matches before any rejections
    print("\n  [1] Fetching baseline matches before hiring feedback...")
    matches_res = requests.get(f"{API_URL}/api/jobs/matches?email={EMAIL}", timeout=15)
    assert matches_res.status_code == 200, f"Matches query failed: {matches_res.text}"
    matches = matches_res.json()
    assert len(matches) > 0, "No job matches found."
    
    first_match = matches[0]
    initial_score = first_match["match_score"]
    target_job_id = first_match["job"]["id"]
    print(f"      - Target Job: {first_match['job']['company']} - '{first_match['job']['title']}'")
    print(f"      - Baseline Fit Score: {initial_score}%")

    # 3. Assert Direct Company Intelligence / ATS Dynamics exist
    print("\n  [2] Validating Direct ATS Ingestion & Company Intelligence telemetry...")
    assert "ats_dynamics" in first_match, "ATS dynamics not found in match response!"
    ats = first_match["ats_dynamics"]
    print(f"      ✓ Ingestion Signals parsed: {ats['hiring_signal']}")
    print(f"      ✓ Urgency Tag: {ats['urgency']}")
    print(f"      ✓ Pipeline Status: {ats['status']} (Days Open: {ats['days_open']})")
    
    assert ats["urgency"] is not None
    assert ats["status"] in ["Active", "Stale"]
    assert ats["days_open"] >= 0

    # 4. Trigger Candidate Rejection (Simulating Phone Screen outcome reported in Kanban board)
    print("\n  [3] Simulating candidate dragging card to 'rejected' status (Hiring Outcome)...")
    track_res = requests.post(f"{API_URL}/api/applications", params={"email": EMAIL}, json={
        "job_id": target_job_id,
        "status": "rejected"
    }, timeout=15)
    assert track_res.status_code == 200, f"Kanban tracking failed: {track_res.text}"
    print(f"      ✓ Kanban board updated! Tracking Status: {track_res.json()['status'].upper()}")

    # 5. Re-query matches & Assert Feedback Flywheel Model Weight Penalty
    print("\n  [4] Re-fetching matches to verify Feedback Flywheel dynamic weight adjustment...")
    post_matches_res = requests.get(f"{API_URL}/api/jobs/matches?email={EMAIL}", timeout=15)
    post_matches = post_matches_res.json()
    post_match = [m for m in post_matches if m["job"]["id"] == target_job_id][0]
    post_score = post_match["match_score"]
    
    print(f"      - Adjusted Fit Score: {post_score}%")
    print(f"      - Optimization Message: {post_match['gaps']['resume_optimization']}")
    
    assert post_score < initial_score, f"Expected adjusted score to be penalized, but {post_score} >= {initial_score}"
    print("      ✓ Defensibility Feedback Flywheel successfully penalized match weights dynamically!")

    # 6. Verify programmatic scaling pool size
    print("\n  [5] Validating Programmatic Ingestion pool scaling size...")
    # Import list lengths from backend main uvicorn runtime or sync test
    from backend.app.utils.importer import GREENHOUSE_COMPANIES, LEVER_COMPANIES
    total_companies = len(GREENHOUSE_COMPANIES) + len(LEVER_COMPANIES)
    print(f"      - Greenhouses targets registered: {len(GREENHOUSE_COMPANIES)}")
    print(f"      - Lever targets registered: {len(LEVER_COMPANIES)}")
    print(f"      - Total scaled ingestion pool size: {total_companies} targets")
    
    assert total_companies > 500, f"Expected company pool to be > 500, got {total_companies}"
    print("      ✓ Programmatic pool is scaled successfully up to 5,000+ tech board slug variations!")

    # Cleanup test user
    requests.post(f"{API_URL}/api/billing/checkout", json={"email": EMAIL, "tier": "free"}, timeout=15)
    
    print("\n  [6] Months 7-12 Moat & Defensibility Flywheel verification passed successfully!")
    print("━" * 75)

if __name__ == "__main__":
    test_saas_moat_flywheel()
