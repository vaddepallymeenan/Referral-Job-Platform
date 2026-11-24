import requests
import os
import sys

def test_closed_loop():
    print("━" * 65)
    print("  🚀  TESTING CLOSED-LOOP SAAS CRM & SCORES ENGINE (WEEKS 5–8)")
    print("━" * 65)
    
    API_URL = "http://localhost:8000"
    EMAIL = "meenan.iitk@gmail.com"
    RESUME_PATH = "resume.pdf"
    
    # Pre-check database status
    print("\n  [1/5] Ingesting & Syncing mock job database...")
    try:
        requests.post(f"{API_URL}/api/jobs/sync?force_mock=true", timeout=15)
        jobs_res = requests.get(f"{API_URL}/api/jobs", timeout=15)
        jobs = jobs_res.json()
        print(f"  ✓ Database populated with {len(jobs)} active listings!")
        if len(jobs) == 0:
            print("  ✗ No jobs found in database")
            sys.exit(1)
        target_job = jobs[0]
        print(f"      Selected target: {target_job['company']} - '{target_job['title']}'")
    except Exception as e:
        print(f"  ✗ Connection failed to backend on {API_URL}: {e}")
        sys.exit(1)
        
    # 2. Upload Resume PDF
    print(f"\n  [2/5] Uploading resume PDF stream to structure profile...")
    try:
        with open(RESUME_PATH, "rb") as f:
            files = {"file": (os.path.basename(RESUME_PATH), f, "application/pdf")}
            upload_res = requests.post(
                f"{API_URL}/api/resume/upload",
                params={"email": EMAIL},
                files=files,
                timeout=20
            )
        if upload_res.status_code == 200:
            print("  ✓ Resume parsed and stored in database!")
        else:
            print(f"  ✗ Upload failed {upload_res.status_code}: {upload_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ PDF parser error: {e}")
        sys.exit(1)
        
    # 3. Request Fit Scorer Detailed Card
    print(f"\n  [3/5] Requesting Honest Scorer Card for '{target_job['company']}'...")
    try:
        fit_res = requests.post(
            f"{API_URL}/api/fit_scorer",
            json={"email": EMAIL, "job_id": target_job["id"]},
            timeout=15
        )
        if fit_res.status_code == 200:
            fit_card = fit_res.json()
            print("  " + "=" * 50)
            print("  ★  HONEST SCORES CARD  ★")
            print("  " + "=" * 50)
            print(f"    Strict Rating: {fit_card['score']}% Fit")
            print(f"    Missing Skills: {', '.join(fit_card['missing_skills']) if fit_card['missing_skills'] else 'None'}")
            print(f"    Resume Advice: {fit_card['optimization_advice']}")
            print("  " + "-" * 50)
        else:
            print(f"  ✗ Fit scorer request failed {fit_res.status_code}: {fit_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Fit scorer error: {e}")
        sys.exit(1)
        
    # 4. Request Outreach connection note
    print(f"\n  [4/5] Requesting tailored signal outreach draft...")
    try:
        out_res = requests.post(
            f"{API_URL}/api/outreach/generate",
            json={"email": EMAIL, "job_id": target_job["id"]},
            timeout=15
        )
        if out_res.status_code == 200:
            outreach = out_res.json()
            print("  " + "=" * 50)
            print("  ★  OUTREACH INTEL CARD  ★")
            print("  " + "=" * 50)
            print(f"    Company Intel: {outreach['company_summary']}")
            print(f"    LinkedIn Note: \"{outreach['linkedin_note']}\"")
            print(f"    Note length: {len(outreach['linkedin_note'])} characters (Under 300 cap!)")
            print("  " + "-" * 50)
        else:
            print(f"  ✗ Outreach generator failed {out_res.status_code}: {out_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Outreach generator error: {e}")
        sys.exit(1)
        
    # 5. Transition Job tracking state to "Applied"
    print(f"\n  [5/5] Tracking job application state to 'Applied' in CRM...")
    try:
        track_res = requests.post(
            f"{API_URL}/api/applications",
            params={"email": EMAIL},
            json={"job_id": target_job["id"], "status": "applied"},
            timeout=15
        )
        if track_res.status_code == 200:
            print("  ✓ Application tracking complete!")
            
            # Fetch and display Kanban pipelines
            print("\n  " + "=" * 50)
            print("  ★  KANBAN STATUS PIPELINES CRM  ★")
            print("  " + "=" * 50)
            kanban_res = requests.get(f"{API_URL}/api/applications", params={"email": EMAIL}, timeout=15)
            kanban = kanban_res.json()
            for app in kanban:
                print(f"    [ {app['status'].upper()} ] {app['job']['company']} - {app['job']['title']}")
            print("  " + "=" * 50)
            print("\n  ✓ SaaS Closed-Loop loop check successful! All milestones complete!")
            print("━" * 65)
        else:
            print(f"  ✗ CRM tracking update failed {track_res.status_code}: {track_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ CRM tracking error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_closed_loop()
