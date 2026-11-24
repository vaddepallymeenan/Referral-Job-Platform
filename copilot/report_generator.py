import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from legacy.fit_scorer import FitScore, UserProfile
from copilot.contact_ranker import RankedContact
from copilot.referral_likelihood_engine import ReferralScore
from copilot.company_strategy_engine import CompanyStrategy

class ReportGenerator:
    def generate_report(self, company_name: str, profile: UserProfile, fit_score: FitScore, referral_score: ReferralScore, strategy: CompanyStrategy, contacts: List[RankedContact], messages: List[Dict[str, Any]]) -> str:
        """
        Assembles all target and candidate data into an incredibly beautiful, premium markdown report.
        """
        
        # 1. Contacts breakdown
        contacts_section = ""
        if contacts:
            for idx, c in enumerate(contacts, start=1):
                email_str = c.email or "Not Found"
                contacts_section += f"""### {idx}. {c.contact_name} — {c.contact_title}
- **LinkedIn:** [{c.linkedin_url}]({c.linkedin_url})
- **Email:** `{email_str}`
- **Priority Score:** {c.priority_score}/30 (Contact Type: {c.contact_type})
- **Why They Matter:** *{c.why_they_matter}*

"""
        else:
            contacts_section = "*No contacts discovered for this company.*\n"

        # 2. Messages section (linked to the top ranked contact)
        messages_section = ""
        if messages and contacts:
            top_c = contacts[0]
            m = messages[0]
            messages_section = f"""### ✉️ Outreach Templates for {top_c.contact_name} ({top_c.contact_title})

#### 1. LinkedIn Connection Note (300 chars limit)
```text
{m.get('connect_note', 'No note generated.')}
```

#### 2. First Cold Message / Email
*Subject:* Quick note from an IIT grad — {company_name}
```text
{m.get('message_draft', 'No draft generated.')}
```

#### 3. Follow-up 1 (Day 3)
```text
{m.get('followup_1', 'No draft generated.')}
```

#### 4. Follow-up 2 (Day 7)
```text
{m.get('followup_2', 'No draft generated.')}
```

#### 5. Cold Email Backup Draft
```text
{m.get('email_draft', 'No draft generated.')}
```
"""
        else:
            messages_section = "*No contacts available for personal message drafting.*\n"

        # Assemble the entire report
        report = f"""# Job Search Outreach Intelligence Report
## Target: {company_name}

---

## 🎯 Strategic Summary
- **Overall Verdict:** **{strategy.verdict}**
- **Action Plan:** *{strategy.action_plan}*
- **Leverage Strategy:** *{strategy.reasoning}*
- **Should Apply Online:** `{"YES" if strategy.should_apply else "NO — Connect via Referral Pathway First"}`

---

## 📊 Opportunity Compatibility Analysis
- **Job Fit Score:** {fit_score.overall_score}/10 — **{fit_score.verdict}**
- **Referral Likelihood:** {referral_score.score}/10 — **{referral_score.referral_path}**

### Dimension Fit Breakdown:
- **Skills Match:** {fit_score.skills.score}/10 — *{fit_score.skills.reason}*
- **Experience Match:** {fit_score.experience.score}/10 — *{fit_score.experience.reason}*
- **Domain Match:** {fit_score.domain.score}/10 — *{fit_score.domain.reason}*
- **Location Match:** {fit_score.location.score}/10 — *{fit_score.location.reason}*
- **Education Match:** {fit_score.education.score}/10 — *{fit_score.education.reason}*

### Identified Gaps to Address:
{chr(10).join(f"- {gap}" for gap in fit_score.all_gaps) if fit_score.all_gaps else "- *No gaps identified!*"}

### Referral Engine Signal:
- *{referral_score.reasoning}*

---

## 🔍 Contact Prioritization & Discovery
{contacts_section}
---

## 📝 Generated Outreach Sequences
{messages_section}
"""
        return report
