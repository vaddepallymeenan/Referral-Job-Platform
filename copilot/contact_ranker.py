import os
import sys
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from legacy.fit_scorer import _get_backend
from legacy.job_pipeline_v2 import Contact

@dataclass
class RankedContact:
    contact_name: str
    contact_title: str
    linkedin_url: str
    email: str
    priority_score: int
    contact_type: str
    why_they_matter: str

class ContactRanker:
    def __init__(self) -> None:
        self.backend, self.backend_name = _get_backend()

    def rank_contacts(self, contacts: List[Contact], hiring_signal: str, institute: str = "") -> List[RankedContact]:
        ranked = []
        for c in contacts:
            name = c.get("contact_name", "")
            title = c.get("contact_title", "")
            linkedin_url = c.get("linkedin_url", "")
            email = c.get("email", "")
            relevance = int(c.get("relevance_score", 0))

            # 1. Classify contact type
            contact_type = self._classify_contact(title)

            # 2. Compute Priority Score
            score = relevance
            
            # Contact type bonus
            if contact_type == "founder":
                score += 5
            elif contact_type == "hiring_manager":
                score += 3
            elif contact_type == "recruiter":
                score += 2

            # Relevance bonus
            if relevance >= 4:
                score += 2

            # Signal bonus
            is_alum = False
            if institute and (institute.lower() in title.lower() or institute.lower() in name.lower() or "alumni" in title.lower()):
                is_alum = True
            
            # Bubble alumni to the top
            if is_alum:
                score += 15
            elif hiring_signal == "alumni":
                score += 10
            elif hiring_signal == "funding":
                score += 8
            elif hiring_signal == "yc_batch":
                score += 6
            elif hiring_signal == "launch":
                score += 4

            # 3. Generate why_they_matter explanation
            why_they_matter = self._generate_why_they_matter(name, title, contact_type, is_alum, hiring_signal)

            ranked.append(RankedContact(
                contact_name=name,
                contact_title=title,
                linkedin_url=linkedin_url,
                email=email,
                priority_score=score,
                contact_type=contact_type,
                why_they_matter=why_they_matter
            ))

        # Sort descending by priority_score
        ranked.sort(key=lambda x: x.priority_score, reverse=True)
        return ranked

    def _classify_contact(self, title: str) -> str:
        t = title.lower()
        mapping = {
            "co-founder":         "founder",
            "founder":            "founder",
            "ceo":                "founder",
            "cto":                "founder",
            "chief":              "founder",
            "talent acquisition": "recruiter",
            "recruiter":          "recruiter",
            "talent":             "recruiter",
            "hr manager":         "recruiter",
            "hr":                 "recruiter",
            "people ops":         "recruiter",
            "people":             "recruiter",
            "head of":            "hiring_manager",
            "vice president":     "hiring_manager",
            "vp":                 "hiring_manager",
            "director":           "hiring_manager",
            "lead":               "hiring_manager",
            "manager":            "hiring_manager",
        }
        for keyword, contact_type in mapping.items():
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, t):
                return contact_type
        return "other"

    def _generate_why_they_matter(self, name: str, title: str, contact_type: str, is_alum: bool, hiring_signal: str) -> str:
        prompt = f"""
        Role: {contact_type}
        Title: {title}
        Is Alumni: {is_alum}
        Hiring Signal: {hiring_signal}
        Explain why this contact matters to an AI/ML candidate's outreach.
        Keep it under 2 sentences. Be specific and tactical.
        """
        
        try:
            if self.backend_name == "mock":
                if is_alum:
                    return f"As a fellow IIT alum, {name} offers an exceptionally high response rate (>60%) and a direct, warm referral pathway into the team."
                elif contact_type == "founder":
                    return f"As a founder/decision-maker at a growing startup, {name} directly shapes the engineering culture and makes immediate hiring decisions."
                elif contact_type == "hiring_manager":
                    return f"As an engineering lead, {name} directly manages the hiring pipeline and can immediately fast-track high-signal technical profiles."
                else:
                    return f"This contact is inside the technical organization and can facilitate introductions or provide team-specific tech stack insights."
            
            response = self.backend.call(prompt).strip()
            response = re.sub(r'\s+', ' ', response)
            return response
        except Exception:
            return f"Key stakeholder in the technical organization who can influence growth and referral loops."
