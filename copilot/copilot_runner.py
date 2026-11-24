import os
import sys
import re
import time
import logging
import traceback
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Tuple
from bs4 import BeautifulSoup
import requests

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from copilot.input_parser import CopilotRequest, CompanyTarget
from legacy.fit_scorer import FitScorer, FitScore
from legacy.job_pipeline_v2 import Enricher, Company, Contact, CFG
from copilot.contact_ranker import ContactRanker, RankedContact
from copilot.alumni_expander import AlumniExpander
from copilot.referral_likelihood_engine import ReferralLikelihoodEngine, ReferralScore
from copilot.company_strategy_engine import CompanyStrategyEngine, CompanyStrategy
from copilot.report_generator import ReportGenerator
from legacy.outreach_engine import MessageComposer

logger = logging.getLogger("copilot.runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

class CopilotRunner:
    def __init__(self, output_dir: str = "output"):
        self.fit_scorer = FitScorer()
        self.enricher = Enricher()
        self.contact_ranker = ContactRanker()
        self.alumni_expander = AlumniExpander()
        self.referral_likelihood_engine = ReferralLikelihoodEngine()
        self.company_strategy_engine = CompanyStrategyEngine()
        self.report_generator = ReportGenerator()
        self.message_composer = MessageComposer()
        
        out_path = Path(output_dir)
        if not out_path.is_absolute():
            self.output_dir = Path(project_root) / out_path
        else:
            self.output_dir = out_path
            
        self.output_dir.mkdir(parents=True, exist_ok=True)


    def run(self, request: CopilotRequest) -> List[Dict[str, Any]]:
        results = []
        logger.info(f"🚀 Starting Copilot Runner for {len(request.targets)} targets.")
        
        for idx, target in enumerate(request.targets, start=1):
            logger.info(f"━━━━ Target {idx}/{len(request.targets)}: {target.name or target.job_url} ━━━━")
            try:
                # 1. Resolve Company Details (scrapes URL or fetches Brave description if needed)
                company_name, jd_text = self._resolve_target_details(target)
                target.name = company_name
                target.job_description = jd_text
                
                logger.info(f"  🏢 Resolved Name: {company_name}")
                logger.info(f"  📝 JD Length: {len(jd_text)} chars")

                # 2. Contact Discovery (Enricher handles both Brave Search contacts and EmailEnricher emails)
                company_payload: Company = {
                    "name": company_name,
                    "source": "funding",
                    "source_url": target.job_url,
                    "hiring_signal": "funding",
                    "job_title": request.user_profile.target_roles[0] if request.user_profile.target_roles else "AI Engineer",
                    "urgency": "1 - Immediate",
                    "company_description": jd_text[:200]
                }

                logger.info(f"  🔍 Discovering general contacts & emails...")
                contacts, accepted, filtered, api_calls, cache_hits, hit_quota = (
                    self.enricher._enrich_company(company_payload)
                )
                logger.info(f"  ✅ Discovered {len(contacts)} general contacts.")

                # 3. Alumni Signals Discovery (IITK, IITD, IITB)
                all_raw_contacts = list(contacts)
                for inst in ["IITK", "IITD", "IITB"]:
                    alum_contacts = self.alumni_expander.expand_alumni(company_name, inst)
                    if alum_contacts:
                        all_raw_contacts.extend(alum_contacts)

                # Deduplicate by linkedin_url
                deduped = {}
                for c in all_raw_contacts:
                    url = c.get("linkedin_url", "").strip()
                    if url:
                        if url not in deduped or (c.get("email") and not deduped[url].get("email")):
                            deduped[url] = c
                merged_contacts = list(deduped.values())

                # 4. Contact Ranking (Bubble alumni to the top & generate why_they_matter)
                logger.info(f"  📊 Ranking {len(merged_contacts)} contacts with alumni signaling...")
                ranked_contacts = self.contact_ranker.rank_contacts(
                    merged_contacts,
                    hiring_signal="funding",
                    institute=request.user_profile.college
                )
                logger.info(f"  ✅ Ranked and sorted contacts.")

                # 5. Fit Scoring
                logger.info(f"  🎯 Running FitScorer...")
                fit_score = self.fit_scorer.score(request.user_profile, jd_text)
                logger.info(f"  ⭐ Fit Score: {fit_score.overall_score}/10 — {fit_score.verdict}")

                # 6. Referral likelihood
                logger.info(f"  🤝 Running ReferralLikelihoodEngine...")
                referral_score = self.referral_likelihood_engine.compute_likelihood(
                    request.user_profile, company_name, ranked_contacts, target.source
                )
                logger.info(f"  🤝 Referral Score: {referral_score.score}/10")

                # 7. Company Strategy
                logger.info(f"  🚀 Running CompanyStrategyEngine...")
                strategy = self.company_strategy_engine.generate_strategy(
                    company_name, "funding", fit_score, referral_score, ranked_contacts
                )
                logger.info(f"  🚀 Verdict: {strategy.verdict}")

                # 8. Outreach Messages (generates all 5 variants per contact)
                logger.info(f"  📝 Generating outreach message templates...")
                
                # Override outreach variables for personalization (using object.__setattr__ to bypass frozen constraints)
                from legacy.job_pipeline_v2 import CFG as LegacyCFG
                from legacy.outreach_engine import CFG as OutreachCFG
                
                object.__setattr__(LegacyCFG, 'CANDIDATE_NAME', request.user_profile.name)
                object.__setattr__(LegacyCFG, 'CANDIDATE_INSTITUTE', request.user_profile.college)
                object.__setattr__(LegacyCFG, 'CANDIDATE_GRAD_YEAR', "2024")
                
                object.__setattr__(OutreachCFG, 'CANDIDATE_NAME', request.user_profile.name)
                object.__setattr__(OutreachCFG, 'CANDIDATE_INSTITUTE', request.user_profile.college)
                object.__setattr__(OutreachCFG, 'CANDIDATE_GRAD_YEAR', "2024")
                if request.user_profile.skills:
                    skills_str = ", ".join(request.user_profile.skills[:5])
                    object.__setattr__(OutreachCFG, 'CANDIDATE_SKILLS', skills_str)


                messages = []
                for c in ranked_contacts:
                    row = pd.Series({
                        "company": company_name,
                        "job_title": request.user_profile.target_roles[0] if request.user_profile.target_roles else "AI Engineer",
                        "contact_name": c.contact_name,
                        "contact_type": c.contact_type,
                        "hiring_signal": "alumni" if "IIT" in c.contact_title or "IIT" in c.contact_name else "funding",
                        "company_description": jd_text[:200]
                    })
                    msg_draft, note, followup_1, followup_2, email_draft = self.message_composer.compose_all(row)
                    messages.append({
                        "connect_note": note,
                        "message_draft": msg_draft,
                        "followup_1": followup_1,
                        "followup_2": followup_2,
                        "email_draft": email_draft
                    })
                logger.info(f"  ✅ Outreach messages drafted.")

                # 9. Generate Report
                logger.info(f"  📄 Assembling final report...")
                report_md = self.report_generator.generate_report(
                    company_name, request.user_profile, fit_score, referral_score, strategy, ranked_contacts, messages
                )
                
                report_path = self.output_dir / f"{sanitize_filename(company_name)}_report.md"
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report_md)
                logger.info(f"  📄 Saved report to: {report_path}")

                results.append({
                    "company_name": company_name,
                    "target": target,
                    "contacts": ranked_contacts,
                    "fit_score": fit_score,
                    "referral_score": referral_score,
                    "strategy": strategy,
                    "messages": messages,
                    "report_path": str(report_path)
                })

            except Exception as e:
                logger.error(f"  ❌ Error processing target {target.name or target.job_url}: {e}")
                logger.error(traceback.format_exc())

        return results

    def _resolve_target_details(self, target: CompanyTarget) -> Tuple[str, str]:
        """
        Resolves the target's company name and job description.
        If target is a URL, scrapes the content.
        If it's just a company name, fetches a generic placeholder or uses Brave.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        if target.job_url:
            try:
                resp = requests.get(target.job_url, headers=headers, timeout=10)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Extract text
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text(separator=" ").strip()
                # Clean up whitespace
                text = re.sub(r'\s+', ' ', text)
                
                # Simple company name heuristic from URL or Title
                title = soup.title.string if soup.title else ""
                company_name = ""
                if "greenhouse.io" in target.job_url:
                    company_name = target.job_url.split("greenhouse.io/")[1].split("/")[0]
                elif "lever.co" in target.job_url:
                    company_name = target.job_url.split("lever.co/")[1].split("/")[0]
                
                if not company_name and title:
                    company_name = title.split("Job")[0].split("Careers")[0].split("-")[0].strip()
                
                if not company_name:
                    company_name = "Unknown Company"
                    
                company_name = company_name.capitalize().replace("_", " ").strip()
                
                return company_name, text[:5000]
            except Exception as e:
                logger.warning(f"Failed to scrape URL {target.job_url}: {e}. Falling back to default.")
                return "Unknown Company", "AI Engineer role at startup. Python, PyTorch, LLMs, MLOps, model deployment, API design."

        company_name = target.name.strip()
        jd_text = ""
        
        if CFG.BRAVE_API_KEY:
            headers = {"Accept": "application/json", "X-Subscription-Token": CFG.BRAVE_API_KEY}
            params = {"q": f"{company_name} startup about what they do tech stack", "count": 3}
            try:
                resp = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=8)
                if resp.status_code == 200:
                    results = resp.json().get("web", {}).get("results", [])
                    snippets = [r.get("description", "") for r in results if r.get("description")]
                    jd_text = " ".join(snippets)
            except Exception as e:
                logger.warning(f"Brave Search about query failed: {e}")

        if not jd_text or len(jd_text) < 100:
            jd_text = (
                f"Machine Learning Engineer / AI Engineer at {company_name}. "
                "We are building next-generation AI agents and foundation models. "
                "Key Responsibilities: Design and deploy end-to-end ML evaluation and training pipelines. "
                "Optimize model inference for scale. Integrate LLMs with web APIs. "
                "Requirements: 1-3 years experience with Python, PyTorch, MLOps (Docker, Kubernetes), "
                "and databases (PostgreSQL, Vector DBs)."
            )

        return company_name, jd_text

def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_\-]', '', name.lower().replace(' ', '_'))
    return cleaned if cleaned else "target_company"

