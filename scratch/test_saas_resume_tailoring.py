import requests
import sys

def test_resume_tailoring_and_prep():
    print("━" * 70)
    print("  🚀 TESTING MONTH 5: DYNAMIC RESUME TAILORING & INTERVIEW PREP")
    print("━" * 70)
    
    API_URL = "http://localhost:8000"
    EMAIL = "meenan.iitk@gmail.com"
    
    # 1. Retrieve Candidate Resume and Job Match List
    print("\n  [1/4] Retrieving candidate matches list from DB...")
    try:
        matches_res = requests.get(f"{API_URL}/api/jobs/matches?email={EMAIL}", timeout=15)
        if matches_res.status_code != 200:
            print(f"  ✗ Matches fetch failed {matches_res.status_code}: {matches_res.text}")
            sys.exit(1)
            
        matches = matches_res.json()
        if not matches:
            print("  ✗ No job matches found. Seed jobs first.")
            sys.exit(1)
            
        selected_match = matches[0] # Grab highest-fit match (OpenAI or Vercel)
        job = selected_match["job"]
        print(f"  ✓ High-fit target selected: {job['company']} — '{job['title']}' (Score: {selected_match['match_score']}% Fit)")
    except Exception as e:
        print(f"  ✗ Connections failed to backend: {e}")
        sys.exit(1)
        
    # 2. Trigger Resume Tailoring API
    print(f"\n  [2/4] Triggering context-aware Resume Bullet Tailoring for {job['company']}...")
    try:
        tailor_payload = {
            "email": EMAIL,
            "job_id": job["id"]
        }
        res = requests.post(f"{API_URL}/api/resume/tailor", json=tailor_payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            bullets = data.get("tailored_bullets", [])
            print(f"  ✓ Suggestions received! Total suggested rewrites: {len(bullets)}")
            assert len(bullets) == 3, f"Expected 3 bullet suggestions, got {len(bullets)}"
            
            print("\n  " + "=" * 65)
            print("  ★  DYNAMIC RESUME BULLET REWRITES (CONTEXT-AWARE)  ★")
            print("  " + "=" * 65)
            for idx, bullet in enumerate(bullets, 1):
                print(f"    {idx}. ORIGINAL BULLET: '{bullet['original_bullet']}'")
                print(f"       TAILORED REWRITE: '{bullet['tailored_bullet']}'")
                print(f"       RATIONALE: {bullet['rationale']}")
                print("    " + "-" * 60)
            print("  " + "=" * 65)
        else:
            print(f"  ✗ Resume tailoring endpoint failed {res.status_code}: {res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Resume tailoring test execution error: {e}")
        sys.exit(1)
        
    # 3. Trigger Interview Prep Generator API
    print(f"\n  [3/4] Generating personalized 10-Question Interview Prep Guide...")
    try:
        prep_payload = {
            "email": EMAIL,
            "job_id": job["id"]
        }
        res = requests.post(f"{API_URL}/api/interview/prep", json=prep_payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            questions = data.get("questions", [])
            print(f"  ✓ Prep guide received! Total curated questions: {len(questions)}")
            assert len(questions) == 10, f"Expected 10 curated questions, got {len(questions)}"
            
            # Print breakdown
            tech_qs = [q for q in questions if q["type"] == "technical"]
            behav_qs = [q for q in questions if q["type"] == "behavioral"]
            print(f"      - Technical Questions: {len(tech_qs)}")
            print(f"      - Behavioral Questions: {len(behav_qs)}")
            
            print("\n  " + "=" * 65)
            print("  ★  PERSONALIZED INTERVIEW PREPARATION SCRIPT  ★")
            print("  " + "=" * 65)
            for q in questions[:4]: # print first 4 for display
                print(f"    Q{q['id']}: {q['question']}")
                print(f"        [Type]: {q['type'].upper()}  |  [Framework]: {q['suggested_framework']}")
                print(f"        [Talking Points]: {q['talking_points']}")
                print("    " + "-" * 60)
            print("    ... and 6 additional highly targeted questions.")
            print("  " + "=" * 65)
        else:
            print(f"  ✗ Interview Prep endpoint failed {res.status_code}: {res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Interview Prep test execution error: {e}")
        sys.exit(1)
        
    # 4. Success check
    print("\n  [4/4] Verification check finished successfully!")
    print("  ✓ Month 5 dynamic tailoring & prep engine is fully operational!")
    print("━" * 70)

if __name__ == "__main__":
    test_resume_tailoring_and_prep()
