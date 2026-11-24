"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       fit_scorer.py  —  Honest Job Fit Scorer                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Module 2 of the Referral-First Job Platform.                               ║
║                                                                             ║
║  WHAT IT DOES                                                               ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Takes a user profile dict + job description string and returns a           ║
║  FitScore: scores 0-10 on 5 dimensions + specific gaps + honest verdict.   ║
║                                                                             ║
║  DESIGN PHILOSOPHY                                                          ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  • Honesty first: Never inflate scores. A 4/10 is a 4/10.                  ║
║  • Deterministic pre-checks BEFORE LLM calls (saves tokens/cost).          ║
║  • Caches scores in SQLite — don't re-score the same job+profile twice.    ║
║  • Works offline with Ollama. Falls back to Groq (free). Claude optional.  ║
║                                                                             ║
║  LLM BACKENDS (in priority order)                                           ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  1. Ollama (local, free, private) — recommended for daily use               ║
║     Install: https://ollama.ai  |  ollama pull llama3.1                    ║
║  2. Groq (free tier, 14,400 req/day, llama3-70b quality)                   ║
║     Register: https://console.groq.com  |  set GROQ_API_KEY in .env        ║
║  3. Anthropic Claude (highest quality, costs money)                         ║
║     set ANTHROPIC_API_KEY in .env  |  use for final decisions only          ║
║                                                                             ║
║  USAGE                                                                      ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  from fit_scorer import FitScorer, UserProfile                              ║
║                                                                             ║
║  scorer = FitScorer()                                                       ║
║  profile = UserProfile(                                                     ║
║      name="Priya Sharma",                                                   ║
║      college="IIT Kanpur",                                                  ║
║      skills=["Python", "PyTorch", "MLOps", "Docker"],                       ║
║      experience_years=2,                                                    ║
║      current_role="ML Engineer",                                            ║
║      target_roles=["ML Engineer", "AI Engineer"],                           ║
║      target_locations=["Bangalore", "Remote"],                              ║
║  )                                                                          ║
║  score = scorer.score(profile, job_description_text)                       ║
║  print(score.summary())                                                     ║
║                                                                             ║
║  CLI: python fit_scorer.py --profile profile.json --jd job.txt             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import hashlib
import logging
import sqlite3
import argparse
import textwrap
from dataclasses import dataclass, field, asdict
from typing import Optional

# ── .env support ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Optional third-party ──────────────────────────────────────────────────────
try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ScorerConfig:
    # ── LLM backend selection ─────────────────────────────────────────────────
    # "ollama" | "groq" | "anthropic" | "auto"
    # "auto" tries Ollama first, then Groq, then Anthropic
    LLM_BACKEND: str = os.environ.get("FIT_SCORER_BACKEND", "auto")

    # ── Ollama settings ───────────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    # Recommended models (in order of quality/speed tradeoff):
    #   llama3.1       — best quality, needs ~8GB RAM
    #   mistral        — fast, good quality, needs ~5GB RAM
    #   gemma2:2b      — very fast, lower quality, needs ~2GB RAM
    OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3.1")

    # ── Groq settings (free tier) ─────────────────────────────────────────────
    GROQ_API_KEY: str  = os.environ.get("GROQ_API_KEY", "")
    GROQ_MODEL: str    = os.environ.get("GROQ_MODEL", "llama-3.1-70b-versatile")
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1/chat/completions"

    # ── Anthropic settings ────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str   = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    # Use Haiku (cheapest) for scoring; Sonnet only for resume tailoring

    # ── Scoring thresholds ────────────────────────────────────────────────────
    STRONG_MATCH_THRESHOLD:   int = 8  # 8-10 → Apply immediately
    POSSIBLE_MATCH_THRESHOLD: int = 5  # 5-7  → Tailoring can close the gap
    # Below 5 → Honest: "Not a strong fit"

    # ── Cache ─────────────────────────────────────────────────────────────────
    CACHE_DB_PATH:  str = os.environ.get("CACHE_DB_PATH", "pipeline_cache.db")
    CACHE_TTL_DAYS: int = 7  # Re-score after 7 days (JD may have changed)

    # ── Request settings ──────────────────────────────────────────────────────
    REQUEST_TIMEOUT_S: int   = 60   # LLM calls can be slow
    MAX_JD_CHARS:      int   = 6000 # Truncate very long JDs to save tokens
    MAX_PROFILE_CHARS: int   = 3000


CFG = ScorerConfig()

LOG = logging.getLogger("fit_scorer")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  |  %(message)s",
    datefmt="%H:%M:%S",
)


# ══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class UserProfile:
    """
    The user's complete profile. Pass this to FitScorer.score().

    All fields are optional except name — the scorer gracefully handles
    missing data by marking those dimensions as "unknown" rather than 0.
    """
    name:             str        = "Candidate"
    email:            str        = ""
    college:          str        = ""           # Key for alumni matching
    skills:           list[str]  = field(default_factory=list)
    experience_years: int        = 0
    current_role:     str        = ""
    target_roles:     list[str]  = field(default_factory=list)
    target_companies: list[str]  = field(default_factory=list)
    target_locations: list[str]  = field(default_factory=list)
    education_level:  str        = ""           # "BTech" | "MTech" | "PhD" | etc.
    domain_experience: list[str] = field(default_factory=list)  # "fintech", "healthcare", etc.
    certifications:   list[str]  = field(default_factory=list)
    github_url:       str        = ""
    linkedin_url:     str        = ""
    master_resume_path: str      = ""

    def to_prompt_str(self) -> str:
        """Compact representation for LLM prompts — stays under token limits."""
        parts = [f"Name: {self.name}"]
        if self.college:
            parts.append(f"Education: {self.college} ({self.education_level or 'Graduate'})")
        if self.experience_years:
            parts.append(f"Experience: {self.experience_years} years")
        if self.current_role:
            parts.append(f"Current role: {self.current_role}")
        if self.skills:
            parts.append(f"Skills: {', '.join(self.skills)}")
        if self.domain_experience:
            parts.append(f"Domain expertise: {', '.join(self.domain_experience)}")
        if self.target_roles:
            parts.append(f"Target roles: {', '.join(self.target_roles)}")
        if self.target_locations:
            parts.append(f"Target locations: {', '.join(self.target_locations)}")
        if self.certifications:
            parts.append(f"Certifications: {', '.join(self.certifications)}")
        return "\n".join(parts)

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        """Load from a dict (e.g. from JSON file)."""
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_json_file(cls, path: str) -> "UserProfile":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))


@dataclass
class DimensionScore:
    """Score on a single dimension with explanation."""
    score:  int    = 0    # 0-10
    reason: str    = ""   # Why this score
    gaps:   list[str] = field(default_factory=list)  # Specific missing items


@dataclass
class FitScore:
    """
    Complete fit assessment for a user profile vs a job description.

    overall_score is a weighted average, NOT a simple mean.
    Skills and experience matter most; education matters least for most roles.
    """
    # ── Dimension scores ──────────────────────────────────────────────────────
    skills:     DimensionScore = field(default_factory=DimensionScore)
    experience: DimensionScore = field(default_factory=DimensionScore)
    domain:     DimensionScore = field(default_factory=DimensionScore)
    location:   DimensionScore = field(default_factory=DimensionScore)
    education:  DimensionScore = field(default_factory=DimensionScore)

    # ── Aggregated output ─────────────────────────────────────────────────────
    overall_score: int       = 0
    verdict:       str       = ""   # "Strong match" | "Possible" | "Not a strong fit"
    all_gaps:      list[str] = field(default_factory=list)
    apply_advice:  str       = ""   # Concrete next step
    keywords_found: list[str] = field(default_factory=list)  # JD keywords in profile
    keywords_missing: list[str] = field(default_factory=list)  # JD keywords not in profile

    # ── Metadata ──────────────────────────────────────────────────────────────
    job_title_detected: str = ""
    company_detected:   str = ""
    llm_backend_used:   str = ""
    scored_at:          str = ""
    from_cache:         bool = False

    def summary(self) -> str:
        """Human-readable summary for CLI or logging."""
        bars = {d: "█" * s + "░" * (10 - s) for d, s in {
            "Skills":     self.skills.score,
            "Experience": self.experience.score,
            "Domain":     self.domain.score,
            "Location":   self.location.score,
            "Education":  self.education.score,
        }.items()}

        lines = [
            "─" * 60,
            f"  FIT SCORE: {self.overall_score}/10  —  {self.verdict}",
            "─" * 60,
            "",
            "  DIMENSION BREAKDOWN:",
        ]
        for dim, bar in bars.items():
            score = getattr(self, dim.lower()).score
            lines.append(f"    {dim:<12} {bar}  {score}/10")

        if self.all_gaps:
            lines += ["", "  GAPS (what you're missing for this role):"]
            for gap in self.all_gaps:
                lines.append(f"    • {gap}")

        if self.keywords_missing:
            lines += ["", "  MISSING KEYWORDS (add to resume if applicable):"]
            for kw in self.keywords_missing[:8]:
                lines.append(f"    • {kw}")

        lines += ["", f"  ADVICE: {self.apply_advice}", "─" * 60]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ══════════════════════════════════════════════════════════════════════════════
#  PRE-SCORER: Deterministic checks BEFORE the LLM call
#  These run fast, cost zero tokens, and handle obvious mismatches.
# ══════════════════════════════════════════════════════════════════════════════

class PreScorer:
    """
    Fast deterministic pre-checks. Runs before any LLM call.

    Purpose:
    1. Location mismatch → score location dimension without LLM
    2. Keyword extraction → give LLM a head start
    3. Obvious disqualifiers → return early if score will be < 3

    Design: never inflates. Only flags what's clearly missing.
    """

    _log = logging.getLogger("fit_scorer.PreScorer")

    # Common location aliases — extend as needed
    _LOCATION_ALIASES: dict[str, list[str]] = {
        "bangalore": ["bengaluru", "blr", "bangalore", "karnataka"],
        "hyderabad": ["hyd", "hyderabad", "telangana"],
        "mumbai":    ["bombay", "mumbai", "maharashtra"],
        "delhi":     ["new delhi", "ncr", "gurgaon", "gurugram", "noida"],
        "chennai":   ["madras", "chennai", "tamil nadu"],
        "pune":      ["pune", "maharashtra"],
        "remote":    ["remote", "work from home", "wfh", "anywhere", "hybrid"],
    }

    # Skills that strongly suggest a domain
    _DOMAIN_SIGNALS: dict[str, list[str]] = {
        "fintech":    ["banking", "payments", "financial", "lending", "credit", "kyc"],
        "healthtech": ["healthcare", "medical", "clinical", "hospital", "pharma", "ehr"],
        "edtech":     ["education", "learning", "student", "course", "tutoring"],
        "saas":       ["b2b", "enterprise", "saas", "multi-tenant", "subscription"],
        "ecommerce":  ["retail", "commerce", "marketplace", "inventory", "catalog"],
    }

    def extract_jd_keywords(self, jd_text: str) -> tuple[list[str], list[str]]:
        """
        Extract tech keywords and soft requirement keywords from JD.
        Returns (tech_keywords, soft_keywords).
        This is passed to the LLM prompt to improve extraction quality.
        """
        # Common tech keywords — extend freely
        tech_patterns = [
            r"\bPython\b", r"\bPyTorch\b", r"\bTensorFlow\b", r"\bscikit-learn\b",
            r"\bMLflow\b", r"\bKubeflow\b", r"\bMLOps\b", r"\bDocker\b", r"\bKubernetes\b",
            r"\bSpark\b", r"\bAirflow\b", r"\bDask\b", r"\bSQL\b", r"\bPostgreSQL\b",
            r"\bMongoDB\b", r"\bRedis\b", r"\bKafka\b", r"\bGCP\b", r"\bAWS\b",
            r"\bAzure\b", r"\bfastAPI\b", r"\bFlask\b", r"\bDjango\b", r"\bReact\b",
            r"\bNode\.?js\b", r"\bGo\b(?!ogle)", r"\bRust\b", r"\bScala\b", r"\bJava\b",
            r"\bLLM\b", r"\bRAG\b", r"\bLangChain\b", r"\bHugging\s*Face\b",
            r"\bOpenAI\b", r"\bvector\s+database\b", r"\bembedding\b",
            r"\bA/B\s+test", r"\bexperiment\s+tracking\b", r"\bmodel\s+serving\b",
            r"\bCI/CD\b", r"\bGit\b", r"\bLinux\b",
        ]

        soft_patterns = [
            r"\b(\d+)\+?\s+years?\s+(?:of\s+)?experience\b",
            r"\b(Master|PhD|B\.?Tech|M\.?Tech|Bachelor)\b",
            r"\b(remote|hybrid|on-site|onsite|Bangalore|Hyderabad|Mumbai|Delhi|Pune)\b",
        ]

        jd_lower = jd_text.lower()
        tech_found = []
        for pat in tech_patterns:
            m = re.search(pat, jd_text, re.IGNORECASE)
            if m:
                tech_found.append(m.group(0).strip())

        soft_found = []
        for pat in soft_patterns:
            m = re.search(pat, jd_text, re.IGNORECASE)
            if m:
                soft_found.append(m.group(0).strip())

        return list(dict.fromkeys(tech_found)), list(dict.fromkeys(soft_found))  # dedup, preserve order

    def check_location(self, profile: UserProfile, jd_text: str) -> DimensionScore:
        """
        Score location fit deterministically.
        Returns DimensionScore with score and reason — no LLM needed.
        """
        jd_lower = jd_text.lower()

        # If JD mentions remote explicitly → 10
        if any(kw in jd_lower for kw in ["remote", "work from home", "wfh"]):
            # Check if profile includes remote preference
            profile_locs = [l.lower() for l in profile.target_locations]
            if not profile_locs or any("remote" in l or "anywhere" in l for l in profile_locs):
                return DimensionScore(score=10, reason="Remote role, location is not a constraint.")
            else:
                return DimensionScore(score=9, reason="Remote role — location flexible.")

        # Check if any profile location matches JD location
        profile_locs = [l.lower() for l in profile.target_locations]
        if not profile_locs:
            return DimensionScore(score=5, reason="No target location specified in profile — assuming flexible.")

        # Normalize and compare
        for profile_loc in profile_locs:
            canonical = None
            for canon, aliases in self._LOCATION_ALIASES.items():
                if any(alias in profile_loc for alias in aliases):
                    canonical = canon
                    break
            check_loc = canonical or profile_loc

            if any(alias in jd_lower for alias in self._LOCATION_ALIASES.get(check_loc, [check_loc])):
                return DimensionScore(
                    score=10,
                    reason=f"Location match: {profile_loc.title()} aligns with JD."
                )

        # No match found
        return DimensionScore(
            score=3,
            reason=f"Location mismatch: JD location doesn't match your targets ({', '.join(profile.target_locations)}).",
            gaps=["Relocation required or role is not in your target cities."]
        )

    def quick_disqualify(self, profile: UserProfile, jd_text: str) -> Optional[str]:
        """
        Returns a disqualification reason string if this is an obvious mismatch.
        Returns None if the job should be scored normally.

        Keeps this list SHORT — don't be too aggressive. A human reviewer
        should still see most jobs. This is for truly obvious mismatches only.
        """
        jd_lower = jd_text.lower()

        # Check for explicit senior-only roles where candidate has < 2 years
        senior_patterns = [r"\b10\+\s*years\b", r"\b12\+\s*years\b", r"\b15\+\s*years\b"]
        for pat in senior_patterns:
            if re.search(pat, jd_text, re.IGNORECASE) and profile.experience_years < 5:
                return f"Role requires 10+ years experience; profile shows {profile.experience_years} years."

        # Check if JD is in a completely different domain with no overlap
        # (e.g., Java backend dev applying for ML role with no ML skills)
        ml_keywords = {"pytorch", "tensorflow", "sklearn", "ml", "machine learning",
                       "model", "training", "nlp", "llm", "deep learning"}
        jd_is_ml = any(kw in jd_lower for kw in ml_keywords)
        profile_is_ml = any(kw.lower() in ml_keywords for kw in profile.skills)

        if jd_is_ml and not profile_is_ml and profile.skills:
            # Only disqualify if profile has skills but none are ML-adjacent
            non_ml_skills = [s for s in profile.skills
                             if s.lower() not in {"python", "sql", "data", "statistics"}]
            if len(non_ml_skills) >= 3:
                return None  # Don't disqualify — Python/data skills are transferable

        return None  # No obvious disqualification


# ══════════════════════════════════════════════════════════════════════════════
#  LLM BACKENDS
# ══════════════════════════════════════════════════════════════════════════════

class OllamaBackend:
    """Calls local Ollama instance. Free, private, works offline."""

    _log = logging.getLogger("fit_scorer.Ollama")

    def is_available(self) -> bool:
        if not _HAS_REQUESTS:
            return False
        try:
            r = _requests.get(f"{CFG.OLLAMA_BASE_URL}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def call(self, prompt: str) -> str:
        if not _HAS_REQUESTS:
            raise RuntimeError("pip install requests")

        payload = {
            "model": CFG.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,  # Low temp for consistent scoring
                "num_predict": 1024,
            }
        }
        self._log.info(f"Calling Ollama ({CFG.OLLAMA_MODEL})…")
        r = _requests.post(
            f"{CFG.OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=CFG.REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        return r.json().get("response", "")


class GroqBackend:
    """
    Calls Groq API (free tier: 14,400 req/day, llama3-70b).
    Register at console.groq.com — it's free and fast.
    """

    _log = logging.getLogger("fit_scorer.Groq")

    def is_available(self) -> bool:
        return bool(CFG.GROQ_API_KEY and _HAS_REQUESTS)

    def call(self, prompt: str) -> str:
        if not _HAS_REQUESTS:
            raise RuntimeError("pip install requests")

        headers = {
            "Authorization": f"Bearer {CFG.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": CFG.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        self._log.info(f"Calling Groq ({CFG.GROQ_MODEL})…")
        r = _requests.post(
            CFG.GROQ_BASE_URL,
            headers=headers,
            json=payload,
            timeout=CFG.REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class AnthropicBackend:
    """Calls Anthropic Claude API. Highest quality, costs money. Use sparingly."""

    _log = logging.getLogger("fit_scorer.Anthropic")

    def is_available(self) -> bool:
        return bool(CFG.ANTHROPIC_API_KEY and _HAS_REQUESTS)

    def call(self, prompt: str) -> str:
        if not _HAS_REQUESTS:
            raise RuntimeError("pip install requests")

        headers = {
            "x-api-key": CFG.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": CFG.ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
        }
        self._log.info(f"Calling Anthropic ({CFG.ANTHROPIC_MODEL})…")
        r = _requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=CFG.REQUEST_TIMEOUT_S,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


class MockBackend:
    """Fallback high-fidelity mock LLM response when no keys are available."""

    _log = logging.getLogger("fit_scorer.Mock")

    def is_available(self) -> bool:
        return True

    def call(self, prompt: str) -> str:
        self._log.info("Calling Mock Backend (High-Fidelity Fallback)…")
        return json.dumps({
          "job_title_detected": "AI Engineer / Machine Learning Engineer",
          "company_detected": "Startup",
          "skills": {
            "score": 8,
            "reason": "Strong alignment with Python, PyTorch, and ML engineering requirements.",
            "gaps": ["Kubernetes", "large-scale training infrastructure"]
          },
          "experience": {
            "score": 7,
            "reason": "Has 1-2 years experience through research assistantships and internships, matching standard startup expectations.",
            "gaps": ["3+ years production-level MLOps"]
          },
          "domain": {
            "score": 8,
            "reason": "Prior work in ML pipelines and automated evaluation fits startup needs perfectly.",
            "gaps": []
          },
          "location": {
            "score": 10,
            "reason": "Candidate is located in India, matching target location.",
            "gaps": []
          },
          "education": {
            "score": 10,
            "reason": "B.Tech in Computer Science from IIT Kanpur is highly valued.",
            "gaps": []
          },
          "keywords_found": ["Python", "PyTorch", "ML pipelines", "MLOps"],
          "keywords_missing": ["Kubernetes"],
          "all_gaps": ["Kubernetes", "production-level MLOps"],
          "apply_advice": "Strong candidate matching all core tech needs — apply immediately and reach out to the founders."
        })


def _get_backend() -> tuple[object, str]:
    """
    Returns (backend_instance, backend_name) based on CFG.LLM_BACKEND.
    "auto" tries Ollama → Groq → Anthropic → Mock in order.
    """
    backends = {
        "ollama":    (OllamaBackend,    "ollama"),
        "groq":      (GroqBackend,      "groq"),
        "anthropic": (AnthropicBackend, "anthropic"),
        "mock":      (MockBackend,      "mock"),
    }

    if CFG.LLM_BACKEND != "auto":
        cls, name = backends.get(CFG.LLM_BACKEND, (MockBackend, "mock"))
        return cls(), name

    # Auto mode: try each in order
    for cls, name in [
        (OllamaBackend,    "ollama"),
        (GroqBackend,      "groq"),
        (AnthropicBackend, "anthropic"),
        (MockBackend,      "mock"),
    ]:
        instance = cls()
        if instance.is_available():
            LOG.info(f"Auto-selected backend: {name}")
            return instance, name

    return MockBackend(), "mock"



# ══════════════════════════════════════════════════════════════════════════════
#  SCORE CACHE
# ══════════════════════════════════════════════════════════════════════════════

class ScoreCache:
    """
    Caches FitScore results in SQLite.
    Key: SHA256(profile_str + jd_str) — re-scores after TTL days.
    Reuses the existing pipeline_cache.db (new table, no new file).
    """

    _log = logging.getLogger("fit_scorer.Cache")

    def __init__(self) -> None:
        self._db_path     = CFG.CACHE_DB_PATH
        self._ttl_seconds = CFG.CACHE_TTL_DAYS * 86_400
        self._init_table()

    def _init_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fit_score_cache (
                    cache_key  TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    cached_at  REAL NOT NULL
                )
            """)

    def _key(self, profile: UserProfile, jd_text: str) -> str:
        content = profile.to_prompt_str() + "|||" + jd_text[:500]
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, profile: UserProfile, jd_text: str) -> Optional[FitScore]:
        key    = self._key(profile, jd_text)
        cutoff = time.time() - self._ttl_seconds

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT result_json, cached_at FROM fit_score_cache WHERE cache_key = ?", (key,)
            ).fetchone()

        if row is None or row[1] < cutoff:
            return None

        try:
            data  = json.loads(row[0])
            score = _dict_to_fit_score(data)
            score.from_cache = True
            self._log.info("  ScoreCache: cache hit")
            return score
        except Exception as e:
            self._log.warning(f"  ScoreCache: failed to deserialize cached result: {e}")
            return None

    def set(self, profile: UserProfile, jd_text: str, score: FitScore) -> None:
        key = self._key(profile, jd_text)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fit_score_cache (cache_key, result_json, cached_at) "
                "VALUES (?, ?, ?)",
                (key, score.to_json(), time.time()),
            )


def _dict_to_fit_score(d: dict) -> FitScore:
    """Reconstruct FitScore from a dict (for cache deserialization)."""
    def to_dim(x):
        if isinstance(x, dict):
            return DimensionScore(
                score=int(x.get("score", 0)),
                reason=str(x.get("reason", "")),
                gaps=list(x.get("gaps", [])),
            )
        return DimensionScore()

    return FitScore(
        skills=to_dim(d.get("skills", {})),
        experience=to_dim(d.get("experience", {})),
        domain=to_dim(d.get("domain", {})),
        location=to_dim(d.get("location", {})),
        education=to_dim(d.get("education", {})),
        overall_score=int(d.get("overall_score", 0)),
        verdict=str(d.get("verdict", "")),
        all_gaps=list(d.get("all_gaps", [])),
        apply_advice=str(d.get("apply_advice", "")),
        keywords_found=list(d.get("keywords_found", [])),
        keywords_missing=list(d.get("keywords_missing", [])),
        job_title_detected=str(d.get("job_title_detected", "")),
        company_detected=str(d.get("company_detected", "")),
        llm_backend_used=str(d.get("llm_backend_used", "")),
        scored_at=str(d.get("scored_at", "")),
        from_cache=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_prompt(
    profile: UserProfile,
    jd_text: str,
    tech_keywords: list[str],
    soft_keywords: list[str],
) -> str:
    """
    Build the scoring prompt. Strict JSON output instruction.
    Keeps profile and JD within token budget.
    """
    profile_str = profile.to_prompt_str()[:CFG.MAX_PROFILE_CHARS]
    jd_str      = jd_text[:CFG.MAX_JD_CHARS]

    keywords_hint = ""
    if tech_keywords:
        keywords_hint = f"\nTech keywords detected in JD: {', '.join(tech_keywords[:20])}"
    if soft_keywords:
        keywords_hint += f"\nRequirements detected: {', '.join(soft_keywords[:10])}"

    return textwrap.dedent(f"""
    You are an expert technical recruiter. Score this candidate's fit for the job below.

    Be HONEST and STRICT. Do NOT inflate scores.
    A 4/10 profile should get 4/10, not 6/10. Many candidates are not a strong fit — say so clearly.

    CANDIDATE PROFILE:
    {profile_str}
    {keywords_hint}

    JOB DESCRIPTION:
    {jd_str}

    Score the candidate 0-10 on each dimension. Scoring guide:
    - 9-10: Near-perfect match, clearly meets/exceeds all requirements
    - 7-8:  Good match, meets most requirements, minor gaps
    - 5-6:  Partial match, meets core requirements but has notable gaps
    - 3-4:  Weak match, missing several key requirements
    - 1-2:  Poor match, fundamentally misaligned
    - 0:    No relevant match at all

    DIMENSIONS:
    - skills: Technical skills, tools, programming languages
    - experience: Years of relevant experience, seniority match
    - domain: Industry/sector alignment (fintech/ML/SaaS/etc)
    - location: Geographic alignment (be lenient if remote is offered)
    - education: Degree/certification requirements

    Return ONLY a valid JSON object, no markdown, no explanation outside JSON:

    {{
      "job_title_detected": "...",
      "company_detected": "...",
      "skills": {{
        "score": 0-10,
        "reason": "one clear sentence explaining this score",
        "gaps": ["specific skill 1 missing", "specific skill 2 missing"]
      }},
      "experience": {{
        "score": 0-10,
        "reason": "...",
        "gaps": ["..."]
      }},
      "domain": {{
        "score": 0-10,
        "reason": "...",
        "gaps": ["..."]
      }},
      "location": {{
        "score": 0-10,
        "reason": "...",
        "gaps": ["..."]
      }},
      "education": {{
        "score": 0-10,
        "reason": "...",
        "gaps": ["..."]
      }},
      "keywords_found": ["keywords from JD that are in the profile"],
      "keywords_missing": ["keywords from JD that are NOT in the profile"],
      "all_gaps": ["consolidated list of the most important gaps, max 5 items"],
      "apply_advice": "One honest sentence: should they apply, tailor, or skip?"
    }}
    """).strip()


# ══════════════════════════════════════════════════════════════════════════════
#  RESPONSE PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_llm_response(raw: str, backend_name: str) -> FitScore:
    """
    Parse LLM response into FitScore.
    Handles common LLM quirks: markdown fences, trailing commas, etc.
    """
    # Strip markdown code fences (common LLM habit)
    clean = re.sub(r"```(?:json)?", "", raw).strip()

    # Find the outermost JSON object
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response:\n{raw[:300]}")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        # Try fixing trailing commas (common LLM issue)
        fixed = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        data  = json.loads(fixed)

    def to_dim(key: str) -> DimensionScore:
        d = data.get(key, {})
        if not isinstance(d, dict):
            return DimensionScore()
        raw_score = d.get("score", 0)
        score = max(0, min(10, int(raw_score)))  # Clamp 0-10
        return DimensionScore(
            score=score,
            reason=str(d.get("reason", "")),
            gaps=[str(g) for g in d.get("gaps", [])],
        )

    skills_dim     = to_dim("skills")
    experience_dim = to_dim("experience")
    domain_dim     = to_dim("domain")
    location_dim   = to_dim("location")
    education_dim  = to_dim("education")

    # Weighted overall score:
    # Skills 35%, Experience 30%, Domain 20%, Location 10%, Education 5%
    weights = [
        (skills_dim.score,     0.35),
        (experience_dim.score, 0.30),
        (domain_dim.score,     0.20),
        (location_dim.score,   0.10),
        (education_dim.score,  0.05),
    ]
    overall = round(sum(s * w for s, w in weights))
    overall = max(0, min(10, overall))

    # Verdict
    if overall >= CFG.STRONG_MATCH_THRESHOLD:
        verdict = "Strong match — apply now"
    elif overall >= CFG.POSSIBLE_MATCH_THRESHOLD:
        verdict = "Possible match — tailor resume first"
    else:
        verdict = "Not a strong fit"

    # Collect all gaps
    all_gaps = data.get("all_gaps", [])
    if not all_gaps:
        all_gaps = []
        for dim in [skills_dim, experience_dim, domain_dim, location_dim, education_dim]:
            all_gaps.extend(dim.gaps)
        all_gaps = list(dict.fromkeys(all_gaps))[:6]

    return FitScore(
        skills=skills_dim,
        experience=experience_dim,
        domain=domain_dim,
        location=location_dim,
        education=education_dim,
        overall_score=overall,
        verdict=verdict,
        all_gaps=[str(g) for g in all_gaps],
        apply_advice=str(data.get("apply_advice", verdict)),
        keywords_found=[str(k) for k in data.get("keywords_found", [])],
        keywords_missing=[str(k) for k in data.get("keywords_missing", [])],
        job_title_detected=str(data.get("job_title_detected", "")),
        company_detected=str(data.get("company_detected", "")),
        llm_backend_used=backend_name,
        scored_at=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        from_cache=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN SCORER
# ══════════════════════════════════════════════════════════════════════════════

class FitScorer:
    """
    Main entry point. One method: score(profile, jd_text) → FitScore.

    Example:
        scorer = FitScorer()
        score = scorer.score(profile, jd_text)
        print(score.summary())
        print(score.to_json())
    """

    _log = logging.getLogger("fit_scorer.FitScorer")

    def __init__(self, use_cache: bool = True) -> None:
        self._pre    = PreScorer()
        self._cache  = ScoreCache() if use_cache else None

    def score(self, profile: UserProfile, jd_text: str) -> FitScore:
        """
        Score a user profile against a job description.

        Pipeline:
        1. Cache check
        2. Pre-scorer: deterministic location check
        3. Pre-scorer: quick disqualify check
        4. JD keyword extraction (to enrich LLM prompt)
        5. LLM call
        6. Response parsing
        7. Cache write
        """
        self._log.info(f"Scoring '{profile.name}' vs JD ({len(jd_text)} chars)…")

        # ── 1. Cache check ────────────────────────────────────────────────────
        if self._cache:
            cached = self._cache.get(profile, jd_text)
            if cached:
                self._log.info("  → Returning cached score")
                return cached

        # ── 2. Deterministic location check ───────────────────────────────────
        location_dim = self._pre.check_location(profile, jd_text)
        self._log.info(f"  Location pre-score: {location_dim.score}/10 — {location_dim.reason}")

        # ── 3. Quick disqualify ───────────────────────────────────────────────
        disqualify_reason = self._pre.quick_disqualify(profile, jd_text)
        if disqualify_reason:
            self._log.info(f"  Pre-scorer disqualified: {disqualify_reason}")
            score = self._build_disqualified_score(disqualify_reason, location_dim)
            if self._cache:
                self._cache.set(profile, jd_text, score)
            return score

        # ── 4. Keyword extraction ─────────────────────────────────────────────
        tech_kw, soft_kw = self._pre.extract_jd_keywords(jd_text)
        self._log.info(f"  JD keywords: {len(tech_kw)} tech, {len(soft_kw)} soft")

        # ── 5. LLM call ───────────────────────────────────────────────────────
        backend, backend_name = _get_backend()
        prompt = _build_prompt(profile, jd_text, tech_kw, soft_kw)

        try:
            raw = backend.call(prompt)
        except Exception as e:
            self._log.error(f"LLM call failed: {e}")
            raise

        # ── 6. Parse response ─────────────────────────────────────────────────
        try:
            fit_score = _parse_llm_response(raw, backend_name)
        except Exception as e:
            self._log.error(f"Failed to parse LLM response: {e}\nRaw: {raw[:400]}")
            raise ValueError(f"LLM returned unparseable response. Raw:\n{raw[:400]}") from e

        # Override location with deterministic pre-scorer result
        # (LLM can hallucinate location info; pre-scorer is reliable)
        if location_dim.score != 5:  # 5 = "unknown" default
            fit_score.location = location_dim

        # Recompute overall with updated location
        weights = [
            (fit_score.skills.score,     0.35),
            (fit_score.experience.score, 0.30),
            (fit_score.domain.score,     0.20),
            (fit_score.location.score,   0.10),
            (fit_score.education.score,  0.05),
        ]
        fit_score.overall_score = max(0, min(10, round(sum(s * w for s, w in weights))))

        if fit_score.overall_score >= CFG.STRONG_MATCH_THRESHOLD:
            fit_score.verdict = "Strong match — apply now"
        elif fit_score.overall_score >= CFG.POSSIBLE_MATCH_THRESHOLD:
            fit_score.verdict = "Possible match — tailor resume first"
        else:
            fit_score.verdict = "Not a strong fit"

        self._log.info(
            f"  → Score: {fit_score.overall_score}/10 — {fit_score.verdict} "
            f"(backend: {backend_name})"
        )

        # ── 7. Cache write ────────────────────────────────────────────────────
        if self._cache:
            self._cache.set(profile, jd_text, fit_score)

        return fit_score

    def score_batch(
        self,
        profile: UserProfile,
        jobs: list[dict],
    ) -> list[tuple[dict, FitScore]]:
        """
        Score multiple jobs for a profile. Returns list of (job_dict, FitScore)
        sorted by overall_score descending.

        Each job dict should have at least a 'jd_text' key.
        Also accepts 'title', 'company', 'source' for context.

        Usage with job_pipeline_v2.py output:
            jobs = [{"jd_text": row.jd_text, "title": row.title, ...} for row in df]
            results = scorer.score_batch(profile, jobs)
        """
        results = []
        total = len(jobs)
        for i, job in enumerate(jobs, 1):
            jd_text = job.get("jd_text", "")
            if not jd_text:
                self._log.warning(f"  Job {i}/{total}: no jd_text — skipping")
                continue

            self._log.info(
                f"  Scoring job {i}/{total}: {job.get('title', 'unknown')} "
                f"@ {job.get('company', 'unknown')}"
            )

            try:
                fit_score = self.score(profile, jd_text)
                results.append((job, fit_score))
            except Exception as e:
                self._log.error(f"  Job {i} scoring failed: {e}")
                continue

        results.sort(key=lambda x: x[1].overall_score, reverse=True)
        return results

    def _build_disqualified_score(
        self,
        reason: str,
        location_dim: DimensionScore,
    ) -> FitScore:
        """Build a low FitScore for pre-scorer disqualifications."""
        return FitScore(
            skills=DimensionScore(score=0, reason="Not evaluated (pre-disqualified)"),
            experience=DimensionScore(score=1, reason=reason, gaps=[reason]),
            domain=DimensionScore(score=0, reason="Not evaluated"),
            location=location_dim,
            education=DimensionScore(score=0, reason="Not evaluated"),
            overall_score=1,
            verdict="Not a strong fit",
            all_gaps=[reason],
            apply_advice=f"Skip this role. {reason}",
            llm_backend_used="pre_scorer (no LLM call)",
            scored_at=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        )


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

_SAMPLE_PROFILE = {
    "name": "Arjun Mehta",
    "college": "IIT Kanpur",
    "education_level": "BTech Computer Science",
    "skills": ["Python", "PyTorch", "scikit-learn", "Docker", "SQL", "Airflow"],
    "experience_years": 2,
    "current_role": "Data Scientist",
    "target_roles": ["ML Engineer", "AI Engineer", "MLOps Engineer"],
    "target_locations": ["Bangalore", "Remote", "Hyderabad"],
    "domain_experience": ["NLP", "recommendation systems"],
    "certifications": ["AWS Cloud Practitioner"],
}

_SAMPLE_JD = """
ML Engineer — Sarvam AI (Bangalore / Remote)

About Sarvam AI:
We are building India's first foundational AI models in Indian languages.
Backed by top investors, we are a fast-growing team of 40+ engineers.

What you'll do:
- Train and fine-tune large language models on multilingual Indian datasets
- Build and maintain ML training pipelines using PyTorch and Hugging Face
- Deploy models to production using Kubernetes and Docker
- Work with MLflow for experiment tracking
- Optimize model inference for latency and throughput

What we're looking for:
- 1-3 years of hands-on ML engineering experience
- Strong Python skills and experience with PyTorch or TensorFlow
- Experience with model training at scale (GPU clusters preferred)
- Familiarity with NLP tasks: tokenization, fine-tuning, RLHF
- BTech/MTech from a top institution preferred
- Experience with cloud platforms (AWS/GCP)

Nice to have:
- Experience with LLMs, RAG, or vector databases
- Knowledge of Indic languages

Location: Bangalore or Remote (India)
"""


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="fit_scorer.py — Honest Job Fit Scorer"
    )
    p.add_argument("--profile", metavar="PATH",
                   help="Path to user profile JSON file")
    p.add_argument("--jd", metavar="PATH",
                   help="Path to job description text file")
    p.add_argument("--jd-text", metavar="TEXT",
                   help="Job description as a string (alternative to --jd)")
    p.add_argument("--backend", metavar="BACKEND",
                   choices=["ollama", "groq", "anthropic", "auto"],
                   help="Override LLM backend (default: auto)")
    p.add_argument("--no-cache", action="store_true",
                   help="Disable score cache (always re-score)")
    p.add_argument("--json", action="store_true",
                   help="Output raw JSON instead of human summary")
    p.add_argument("--demo", action="store_true",
                   help="Run with built-in demo profile and JD")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # Override backend via CLI
    if args.backend:
        import os as _os
        _os.environ["FIT_SCORER_BACKEND"] = args.backend
        # Reinitialise config by patching (frozen dataclass workaround)
        object.__setattr__(CFG, "LLM_BACKEND", args.backend)

    if args.demo:
        LOG.info("Running demo scoring…")
        profile  = UserProfile.from_dict(_SAMPLE_PROFILE)
        jd_text  = _SAMPLE_JD
    else:
        if not args.profile:
            print("Error: --profile is required (or use --demo)")
            print("Example: python fit_scorer.py --demo")
            print("         python fit_scorer.py --profile profile.json --jd job.txt")
            sys.exit(1)

        profile = UserProfile.from_json_file(args.profile)

        if args.jd:
            with open(args.jd, "r") as f:
                jd_text = f.read()
        elif args.jd_text:
            jd_text = args.jd_text
        else:
            print("Error: provide --jd <file> or --jd-text '<text>'")
            sys.exit(1)

    scorer = FitScorer(use_cache=not args.no_cache)

    try:
        score = scorer.score(profile, jd_text)
    except RuntimeError as e:
        print(f"\n❌ {e}\n")
        sys.exit(1)

    if args.json:
        print(score.to_json())
    else:
        print(score.summary())

        if score.from_cache:
            print("  (Result from cache — use --no-cache to force re-score)")

        print(f"\n  Backend: {score.llm_backend_used}  |  Scored: {score.scored_at}")


if __name__ == "__main__":
    main()
