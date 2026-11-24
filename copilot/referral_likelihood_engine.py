import os
import sys
import re
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from legacy.fit_scorer import _get_backend, UserProfile
from copilot.contact_ranker import RankedContact

@dataclass
class ReferralScore:
    score: int
    reasoning: str
    referral_path: str

class ReferralLikelihoodEngine:
    def __init__(self) -> None:
        self.backend, self.backend_name = _get_backend()

    def compute_likelihood(self, profile: UserProfile, company_name: str, contacts: List[RankedContact], hiring_signal: str) -> ReferralScore:
        score = 3  # baseline score for a typical cold opportunity
        referral_path = "No direct path identified. Standard cold outreach required."

        # Check for alumni in contacts
        has_alum = False
        alum_name = ""
        alum_title = ""
        
        # Check if candidate has college
        candidate_college = (profile.college or "").lower()

        for c in contacts:
            title_lower = c.contact_title.lower()
            name_lower = c.contact_name.lower()
            
            # Match college name or general alumni keyword
            if candidate_college and (candidate_college in title_lower or candidate_college in name_lower or "alumni" in title_lower):
                has_alum = True
                alum_name = c.contact_name
                alum_title = c.contact_title
                break
            
            # General "IIT" cross-match bonus
            if "iit" in title_lower or "iit" in name_lower:
                has_alum = True
                alum_name = c.contact_name
                alum_title = c.contact_title
                break

        if has_alum:
            score = 9
            referral_path = f"Direct Alumni Connection identified: {alum_name} ({alum_title}). High conversion referral path available."
        elif hiring_signal == "funding" or hiring_signal == "yc_batch":
            # Check if any founders are in contacts
            has_founder = any(c.contact_type == "founder" for c in contacts)
            if has_founder:
                score = 7
                referral_path = "Founder direct outreach available on an active funding signal. High potential peer interaction."
            else:
                score = 5
                referral_path = "Active company signal detected. Cold outreach to engineering leaders recommended."
        else:
            # Recruiter only check
            has_recruiter = any(c.contact_type == "recruiter" for c in contacts)
            if has_recruiter:
                score = 4
                referral_path = "Recruiter outreach path available. Higher competition, standard application backup recommended."

        # Compute reasoning via LLM call (1 prompt)
        reasoning = self._generate_reasoning(profile, company_name, score, referral_path, hiring_signal)

        return ReferralScore(score=score, reasoning=reasoning, referral_path=referral_path)

    def _generate_reasoning(self, profile: UserProfile, company_name: str, score: int, referral_path: str, hiring_signal: str) -> str:
        prompt = f"""
        Candidate College: {profile.college}
        Target Company: {company_name}
        Referral Score: {score}/10
        Referral Path: {referral_path}
        Hiring Signal: {hiring_signal}
        Explain why this referral likelihood score is given and how they can best utilize the identified path.
        Keep it to exactly 2 concise, highly strategic sentences.
        """
        
        try:
            if self.backend_name == "mock":
                if score >= 8:
                    return f"A referral likelihood of {score}/10 is established due to an identified fellow IIT alumnus at {company_name}. Reaching out to them using warm alumni hooks will bypass traditional screening and lead directly to internal referral loops."
                elif score >= 6:
                    return f"A referral score of {score}/10 is supported by the active growth signal and direct founder access. Founder outreach at this stage yields high response rates if centered around peer-to-peer technical alignment."
                else:
                    return f"A conservative score of {score}/10 reflects the absence of immediate warm paths. Focus on cold outreach to technical managers highlighting specific projects before fallback recruiter contact."
            
            response = self.backend.call(prompt).strip()
            response = re.sub(r'\s+', ' ', response)
            return response
        except Exception:
            return f"Calculated based on active hiring signals and technical overlap. Leverage direct peer cold outreach to maximize reply rates."
