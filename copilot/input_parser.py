import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.app.utils.parser import extract_text_from_pdf, parse_resume_to_json
from legacy.fit_scorer import UserProfile

@dataclass
class CompanyTarget:
    name: str
    job_url: str = ""
    job_description: str = ""
    source: str = "manual"

@dataclass
class CopilotRequest:
    user_profile: UserProfile
    targets: List[CompanyTarget]

def parse_input(resume_path: str, targets_raw: List[str]) -> CopilotRequest:
    """
    Parses resume PDF to UserProfile and normalizes targets list.
    """
    # 1. Parse Resume
    if not os.path.exists(resume_path):
        raise FileNotFoundError(f"Resume PDF not found: {resume_path}")
        
    with open(resume_path, "rb") as f:
        pdf_bytes = f.read()
        
    raw_text = extract_text_from_pdf(pdf_bytes)
    parsed_json = parse_resume_to_json(raw_text)
    
    # Fallback to env vars if parser returns empty/mock values
    name = parsed_json.get("name") or os.environ.get("CANDIDATE_NAME", "Candidate")
    email = parsed_json.get("email") or os.environ.get("GMAIL_USER", "")
    phone = parsed_json.get("phone") or os.environ.get("CANDIDATE_PHONE", "")
    skills = parsed_json.get("skills") or [s.strip() for s in os.environ.get("CANDIDATE_SKILLS", "").split(",")]
    
    college = ""
    if parsed_json.get("education"):
        college = parsed_json.get("education")[0].get("institution", "")
    if not college:
        college = os.environ.get("CANDIDATE_INSTITUTE", "")

    # Clean/normalize college string to match alumni logic (e.g. "IIT Kanpur" or "IITK")
    if "kanpur" in college.lower() or "iitk" in college.lower():
        college = "IIT Kanpur"

    experience = parsed_json.get("experience", [])
    current_role = experience[0].get("role", "") if experience else ""
    
    profile = UserProfile(
        name=name,
        email=email,
        college=college,
        skills=skills,
        experience_years=len(experience),  # Simple heuristic fallback
        current_role=current_role,
        target_roles=parsed_json.get("target_roles") or ["Machine Learning Engineer", "AI Engineer", "MLOps Engineer"],
        target_locations=["India", "Remote"]
    )
    
    # 2. Normalize Targets
    targets = []
    for raw in targets_raw:
        raw = raw.strip()
        if not raw:
            continue
        
        if raw.startswith("http://") or raw.startswith("https://"):
            targets.append(CompanyTarget(name="", job_url=raw, source="url"))
        else:
            targets.append(CompanyTarget(name=raw, source="manual"))
            
    return CopilotRequest(user_profile=profile, targets=targets)
