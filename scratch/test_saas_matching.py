import requests
import os
import sys

def test_matching_flow():
    print("━" * 60)
    print("  🚀  TESTING SAAS CORE MATCHING & DATABASE LOOP (WEEKS 1–4)")
    print("━" * 60)
    
    API_URL = "http://localhost:8000"
    EMAIL = "meenan.iitk@gmail.com"
    RESUME_PATH = "resume.pdf"
    
    # 1. Sync Job Listings from Greenhouse & Lever
    print("\n  [1/3] Triggering Daily public ATS Ingestion...")
    try:
        sync_res = requests.post(f"{API_URL}/api/jobs/sync?force_mock=true", timeout=30)
        if sync_res.status_code == 200:
            print(f"  ✓ Sync successful! Response: {sync_res.json()}")
        else:
            print(f"  ✗ Sync status error {sync_res.status_code}: {sync_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Failed to reach API on {API_URL}: {e}")
        sys.exit(1)
        
    # 2. Upload Candidate Resume PDF and Structure via Gemini
    print(f"\n  [2/3] Uploading PDF: {RESUME_PATH}...")
    if not os.path.exists(RESUME_PATH):
        print(f"  ✗ PDF not found at {RESUME_PATH}")
        sys.exit(1)
        
    try:
        with open(RESUME_PATH, "rb") as f:
            files = {"file": (os.path.basename(RESUME_PATH), f, "application/pdf")}
            upload_res = requests.post(
                f"{API_URL}/api/resume/upload",
                params={"email": EMAIL},
                files=files,
                timeout=30
            )
            
        if upload_res.status_code == 200:
            profile = upload_res.json()
            print(f"  ✓ Parse successful!")
            print(f"    Name parsed: {profile['structured_json']['name']}")
            print(f"    Skills extracted: {', '.join(profile['structured_json']['skills'][:6])}...")
        else:
            print(f"  ✗ Upload failed {upload_res.status_code}: {upload_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Upload error: {e}")
        sys.exit(1)
        
    # 3. Retrieve Ranked Curation Matches (Top 10 pgvector/cosine matches)
    print("\n  [3/3] Retrieving top 10 honest match rankings...")
    try:
        matches_res = requests.get(
            f"{API_URL}/api/jobs/matches",
            params={"email": EMAIL},
            timeout=20
        )
        if matches_res.status_code == 200:
            matches = matches_res.json()
            print(f"  ✓ Matches retrieved: {len(matches)} listings found!")
            print("\n  " + "=" * 50)
            print("  ★  BRUTAL CURATION QUEUE (TOP MATCHES)  ★")
            print("  " + "=" * 50)
            
            for idx, match in enumerate(matches, 1):
                job = match["job"]
                score = match["match_score"]
                gaps = match["gaps"]["missing_skills"]
                
                print(f"  {idx:02d}. {score}% Match | {job['company']} - {job['title']}")
                print(f"      Platform: {job['ats_type']} | URL: {job['url'][:60]}...")
                if gaps:
                    print(f"      🚨 Missing Skills: {', '.join(gaps)}")
                else:
                    print("      ✓ Skill alignment perfect!")
                print("  " + "-" * 50)
                
            print("\n  ✓ Milestone verification completed successfully!")
            print("━" * 60)
        else:
            print(f"  ✗ Matches calculation failed {matches_res.status_code}: {matches_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Matches calculation error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_matching_flow()
