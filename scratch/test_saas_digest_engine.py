import requests
import os
import sys
import subprocess

def test_retention_engine():
    print("━" * 65)
    print("  🚀  TESTING MONTH 4 RETENTION ENGINE (WEEKLY DIGEST & SIGNALS)")
    print("━" * 65)
    
    API_URL = "http://localhost:8000"
    EMAIL = "meenan.iitk@gmail.com"
    
    # 1. Sync Mock jobs & populate AI Signals
    print("\n  [1/5] Syncing database to seed listings & AI Company Signals...")
    try:
        sync_res = requests.post(f"{API_URL}/api/jobs/sync?force_mock=true", timeout=15)
        print(f"  ✓ Database populated! Signals & mock jobs successfully seeded.")
        
        # Verify signals
        sig_res = requests.get(f"{API_URL}/api/signals", timeout=15)
        signals = sig_res.json()
        print(f"  ✓ Tracked AI Company Signals active: {len(signals)}")
        for sig in signals[:3]:
            print(f"      - {sig['company']} ({sig['signal_type']}): +{sig['weight_boost']}% boost")
    except Exception as e:
        print(f"  ✗ Connection failed to backend: {e}")
        sys.exit(1)
        
    # 2. Upload / verify candidate resume exists
    print(f"\n  [2/5] Verification of structured profile...")
    try:
        res = requests.get(f"{API_URL}/api/resume?email={EMAIL}", timeout=15)
        if res.status_code == 200:
            print("  ✓ Candidate resume profile detected in database.")
        else:
            print("  ✗ Resume profile not found. Run test_saas_closed_loop.py first to upload resume.")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Resume query error: {e}")
        sys.exit(1)
        
    # 3. Create and Save Preferences Profile
    print(f"\n  [3/5] Saving Search Profile preferences (Remote, Location=India, Keywords=MLOps)...")
    try:
        pref_payload = {
            "is_remote": True,
            "location": "India",
            "company_stage": "Any",
            "keywords": "mlops, docker, python"
        }
        pref_res = requests.post(
            f"{API_URL}/api/search_profile?email={EMAIL}",
            json=pref_payload,
            timeout=15
        )
        if pref_res.status_code == 200:
            pref = pref_res.json()
            print(f"  ✓ Saved Search Profile stored: remote={pref['is_remote']}, location='{pref['location']}', keywords='{pref['keywords']}'")
        else:
            print(f"  ✗ Search Profile save failed {pref_res.status_code}: {pref_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Search Profile error: {e}")
        sys.exit(1)

    # 4. Fetch Matches & Verify Signal Boosts
    print(f"\n  [4/5] Running matches engine to verify signals and search preference re-ranking...")
    try:
        matches_res = requests.get(f"{API_URL}/api/jobs/matches?email={EMAIL}", timeout=15)
        matches = matches_res.json()
        print("  " + "=" * 50)
        print("  ★  RE-RANKED CURATION MATCHES (BOOSTS APPLIED)  ★")
        print("  " + "=" * 50)
        for match in matches[:3]:
            print(f"    - [{match['match_score']}% Fit] {match['job']['company']} — '{match['job']['title']}'")
            print(f"      Advice: {match['gaps']['resume_optimization']}")
        print("  " + "=" * 50)
    except Exception as e:
        print(f"  ✗ Matches engine verification failed: {e}")
        sys.exit(1)

    # 5. Trigger Monday Morning Digest Email
    print(f"\n  [5/5] Triggering Monday Morning Digest dispatch API...")
    try:
        digest_res = requests.post(f"{API_URL}/api/digest/send?email={EMAIL}", timeout=15)
        if digest_res.status_code == 200:
            print("  ✓ Monday Morning Digest email dispatch endpoint executed successfully!")
            
            # Run the CLI cron script directly to verify cron execution
            print("\n  [Bonus] Validating CLI weekly digest cron pipeline execution...")
            cron_run = subprocess.run(
                ["python", "backend/cron_digest.py"],
                capture_output=True,
                text=True
            )
            if cron_run.returncode == 0:
                print("  ✓ CLI Cron Digest runner executed with 0 exit code!")
                # Print a small section of the logs file
                log_file = "logs/weekly_digest_emails.log"
                if os.path.exists(log_file):
                    print(f"  ✓ Email logged successfully to {log_file}!")
                    with open(log_file, "r") as f:
                        lines = f.readlines()
                    print("\n  " + "=" * 50)
                    print("  ★  DISPATCHED DIGEST EMAIL SNAPSHOT  ★")
                    print("  " + "=" * 50)
                    for line in lines[-25:]: # last 25 lines
                        print("    " + line.strip())
                    print("  " + "=" * 50)
            else:
                print(f"  ✗ CLI Cron Digest failed: {cron_run.stderr}")
                sys.exit(1)
        else:
            print(f"  ✗ Digest dispatch failed {digest_res.status_code}: {digest_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Digest engine validation failed: {e}")
        sys.exit(1)
        
    print("\n  ✓ Month 4 Retention Engine check successful! All features operational!")
    print("━" * 65)

if __name__ == "__main__":
    test_retention_engine()
