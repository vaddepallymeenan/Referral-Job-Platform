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

from legacy.fit_scorer import _get_backend, FitScore
from copilot.contact_ranker import RankedContact
from copilot.referral_likelihood_engine import ReferralScore

@dataclass
class CompanyStrategy:
    verdict: str  # PRIORITIZE, APPLY, or SKIP
    action_plan: str
    reasoning: str
    outreach_order: List[str]
    should_apply: bool

class CompanyStrategyEngine:
    def __init__(self) -> None:
        self.backend, self.backend_name = _get_backend()

    def generate_strategy(self, company_name: str, hiring_signal: str, fit_score: FitScore, referral_score: ReferralScore, contacts: List[RankedContact]) -> CompanyStrategy:
        # 1. Decision Tree for Verdict
        overall = fit_score.overall_score
        ref_score = referral_score.score
        
        should_apply = True
        outreach_order = []

        if overall >= 8 and ref_score >= 8:
            verdict = "PRIORITIZE"
            action_plan = "Contact alumni immediately to secure a referral. Do not apply directly online yet to avoid resume filter lock."
            should_apply = False  # referral first!
        elif overall >= 7 or ref_score >= 6:
            verdict = "APPLY"
            action_plan = "Apply directly to the role online, then immediately follow up with the founders or hiring managers."
            should_apply = True
        else:
            verdict = "SKIP"
            action_plan = "Low overall compatibility. Skip this opportunity or contact founders solely to build future connection capital."
            should_apply = False

        # Build outreach order based on contact ranking
        for c in contacts[:3]:
            outreach_order.append(f"{c.contact_name} ({c.contact_title})")

        # 2. Generate strategic reasoning via LLM
        reasoning = self._generate_strategic_reasoning(company_name, verdict, overall, ref_score, action_plan)

        return CompanyStrategy(
            verdict=verdict,
            action_plan=action_plan,
            reasoning=reasoning,
            outreach_order=outreach_order,
            should_apply=should_apply
        )

    def _generate_strategic_reasoning(self, company_name: str, verdict: str, fit_score: int, ref_score: int, action_plan: str) -> str:
        prompt = f"""
        Company: {company_name}
        Verdict: {verdict}
        Fit Score: {fit_score}/10
        Referral Score: {ref_score}/10
        Action Plan: {action_plan}
        Explain why this strategy is the absolute highest leverage path for this candidate.
        Keep it to 2 highly strategic and tactical sentences.
        """

        try:
            if self.backend_name == "mock":
                if verdict == "PRIORITIZE":
                    return f"With a fit score of {fit_score}/10 and a warm alumni referral path, {company_name} represents a top-tier opportunity. Prioritizing warm alumni channels guarantees your profile lands on the hiring manager's desk rather than being lost in standard job board queues."
                elif verdict == "APPLY":
                    return f"This opportunity represents a solid technical match. Applying directly while executing targeted outreach to senior engineering leaders maximizes visibility and secures a fast-tracked interview loop."
                else:
                    return f"Due to lower technical compatibility, standard applications are highly inefficient. Focus instead on higher fit targets to maximize return on outreach effort."
            
            response = self.backend.call(prompt).strip()
            response = re.sub(r'\s+', ' ', response)
            return response
        except Exception:
            return f"Strategically optimized for candidate's IIT cohort and technical alignment. Focus outreach on top decision makers to bypass cold queues."
