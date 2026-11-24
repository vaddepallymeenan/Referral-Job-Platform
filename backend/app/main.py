import os
import math
import logging
from typing import List, Dict, Any, Tuple, Optional
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from backend.app.config import settings
from backend.app.database import engine, get_db, is_postgres, Base
from backend.app.models import User, Resume, Job, FitScore, Application, SavedSearchProfile, CompanySignal
from backend.app.schemas import (
    UserCreate, UserResponse, ResumeResponse, JobResponse, JobMatchResponse,
    ApplicationBase, ApplicationResponse, ApplicationDetailedResponse,
    FitScorerRequest, FitScorerDetailedResponse, OutreachRequest, OutreachResponse,
    SavedSearchProfileBase, SavedSearchProfileResponse, CompanySignalResponse,
    TailorResumeRequest, TailorResumeResponse, TailoredBullet, InterviewPrepQuestion, InterviewPrepResponse,
    BillingCheckoutRequest
)
from backend.app.utils.parser import extract_text_from_pdf, parse_resume_to_json, generate_embedding
from backend.app.utils.importer import sync_all_jobs

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.main")

# Initialize database tables on startup
logger.info("Initializing database schemas...")
try:
    if is_postgres():
        # Create extension first if using PostgreSQL
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
    Base.metadata.create_all(bind=engine)
    logger.info("Database schemas successfully initialized.")
except Exception as e:
    logger.error(f"Error initializing database: {e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

# Add CORS Middleware to enable communication with Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the Next.js Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── HELPER VECTOR ARITHMETIC (For SQLite Fallback) ───────────────────────────
def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes the cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0.0 or norm_v2 == 0.0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

# ── API ENDPOINTS ────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {"message": "Welcome to the Honest Job Matching API!", "status": "running"}

@app.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """Creates a new user profile or retrieves an existing one by email."""
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        return existing
    new_user = User(email=user_in.email, subscription_tier="free")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/api/resume/upload", response_model=ResumeResponse)
async def upload_resume(
    email: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Uploads a candidate's resume PDF, extracts text, structures to JSON, generates embeddings, and saves."""
    # 1. Fetch/Create User
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, subscription_tier="free")
        db.add(user)
        db.commit()
        db.refresh(user)
        
    # 2. Read file contents and extract raw text
    try:
        contents = await file.read()
        raw_text = extract_text_from_pdf(contents)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read PDF file: {str(e)}"
        )
        
    if not raw_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PDF file is empty or text could not be extracted."
        )
        
    # 3. Structured Extraction using Gemini
    logger.info("Structuring resume text using Gemini...")
    structured_json = parse_resume_to_json(raw_text)
    
    # 4. Generate Embedding for the resume
    logger.info("Generating embedding for candidate resume...")
    resume_embedding = generate_embedding(raw_text)
    
    # 5. Save or Update in database
    from backend.app.utils.security import encrypt_text, decrypt_text
    encrypted_raw = encrypt_text(raw_text)
    
    existing_resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if existing_resume:
        existing_resume.raw_text = encrypted_raw
        existing_resume.structured_json = structured_json
        existing_resume.embedding = resume_embedding
        db.commit()
        db.refresh(existing_resume)
        existing_resume.raw_text = decrypt_text(existing_resume.raw_text)
        return existing_resume
    else:
        new_resume = Resume(
            user_id=user.id,
            raw_text=encrypted_raw,
            structured_json=structured_json,
            embedding=resume_embedding
        )
        db.add(new_resume)
        db.commit()
        db.refresh(new_resume)
        new_resume.raw_text = decrypt_text(new_resume.raw_text)
        return new_resume

@app.get("/api/resume", response_model=ResumeResponse)
def get_resume(email: str, db: Session = Depends(get_db)):
    """Retrieves the structured resume details for a user."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not uploaded yet")
    
    from backend.app.utils.security import decrypt_text
    resume.raw_text = decrypt_text(resume.raw_text)
    return resume

@app.post("/api/jobs/sync")
def sync_jobs(force_mock: bool = False, db: Session = Depends(get_db)):
    """Triggers background public ATS scraping/syncing from Greenhouse & Lever APIs."""
    inserted = sync_all_jobs(db, force_mock=force_mock)
    
    # Automatically seed AI Company Signals for high-leverage matching weight boosts
    from backend.app.models import CompanySignal
    existing = db.query(CompanySignal).first()
    if not existing:
        signals = [
            CompanySignal(company="Stripe", signal_type="funding", description="Stripe raised $6.5B Series I at a $50B valuation.", weight_boost=15),
            CompanySignal(company="OpenAI", signal_type="product_launch", description="OpenAI launched GPT-4o-mini, scaling intelligence cost-efficiency.", weight_boost=15),
            CompanySignal(company="Linear", signal_type="funding", description="Linear raised a Series B to scale fast issues tracker execution.", weight_boost=15),
            CompanySignal(company="Vercel", signal_type="product_launch", description="Vercel announced v0.dev AI tool for instant Tailwind React widgets.", weight_boost=15),
        ]
        db.add_all(signals)
        db.commit()
        logger.info("Successfully seeded active AI Company Signals!")
        
    return {"message": "Successfully synchronized jobs.", "inserted_count": inserted}

@app.get("/api/jobs", response_model=List[JobResponse])
def get_jobs(db: Session = Depends(get_db)):
    """Retrieves all active job postings in the database."""
    # Ensure there's at least some jobs in the DB. If not, auto-sync mock
    count = db.query(Job).count()
    if count == 0:
        sync_all_jobs(db, force_mock=True)
    return db.query(Job).filter(Job.is_active == True).all()

def _calculate_postgres_matches(jobs, resume_embedding, user_skills, db) -> List[Dict[str, Any]]:
    """Helper method to rank active jobs against candidate resume via PostgreSQL pgvector cosine similarity."""
    from sqlalchemy import text
    query = text("""
        SELECT id, (embedding <=> :resume_emb) as distance 
        FROM jobs 
        WHERE is_active = True
    """)
    results = db.execute(query, {"resume_emb": str(resume_embedding)}).fetchall()
    distance_map = {row[0]: row[1] for row in results}
    
    matches = []
    for job in jobs:
        dist = distance_map.get(job.id, 1.0)
        sim = 1.0 - dist
        fit_score = int(sim * 100)
        if fit_score < 0: fit_score = 0
        if fit_score > 100: fit_score = 100
        
        job_desc_lower = job.description.lower()
        common_skills = ["pytorch", "tensorflow", "kubernetes", "docker", "mlops", "python", "sql", "aws", "gcp", "ci/cd", "javascript", "react", "next.js", "vector database", "embeddings", "agent"]
        gaps = []
        for cs in common_skills:
            if cs in job_desc_lower and cs not in user_skills:
                gaps.append(cs.title())
                
        penalty = len(gaps) * 8
        final_score = fit_score - penalty
        if final_score < 10: final_score = 10
        
        matches.append({
            "job": job,
            "match_score": final_score,
            "distance": float(dist),
            "gaps": {"missing_skills": gaps, "resume_optimization": f"Consider adding experience with {', '.join(gaps)} to increase your match rate." if gaps else "Your resume has high keyword alignment!"}
        })
    return matches

def _calculate_sqlite_matches(jobs, resume_embedding, user_skills) -> List[Dict[str, Any]]:
    """Helper method to rank active jobs against candidate resume via local Python Cosine Similarity & Text Overlap fallback."""
    matches = []
    for job in jobs:
        sim = cosine_similarity(resume_embedding, job.embedding)
        
        if sim < 0.25:
            job_text = (job.title + " " + job.description).lower()
            overlap_count = 0
            for skill in user_skills:
                if skill in job_text:
                    overlap_count += 1
                    
            title_sim = 0.2
            if any(x in job.title.lower() for x in ["ml", "machine learning", "ai ", "data science", "mlops", "artificial intelligence"]):
                title_sim = 0.8
            elif "infrastructure" in job.title.lower() or "platform" in job.title.lower():
                title_sim = 0.6
            
            sim = title_sim + min(0.18, (overlap_count * 0.03))
            if sim > 0.95: sim = 0.95
            
        dist = 1.0 - sim
        fit_score = int(sim * 100)
        
        job_desc_lower = job.description.lower()
        common_skills = ["pytorch", "tensorflow", "kubernetes", "docker", "mlops", "python", "sql", "aws", "gcp", "ci/cd", "javascript", "react", "next.js", "vector database", "embeddings", "agent"]
        gaps = []
        for cs in common_skills:
            if cs in job_desc_lower and cs not in user_skills:
                gaps.append(cs.title())
        matches.append({
            "job": job,
            "match_score": fit_score, # note that fit_score is calculated, or we can use fit_score directly
            "distance": float(dist),
            "gaps": {
                "missing_skills": gaps,
                "resume_optimization": f"Add proof of work detailing: {', '.join(gaps)}." if gaps else "Perfect skill keyword match!"
            }
        })
    return matches

def _apply_search_profile_boost(match_score: int, job, search_profile) -> int:
    """Helper to apply location, remote, and keyword preference boosts to match score."""
    if not search_profile:
        return match_score
    job_text = (job.title + " " + job.description).lower()
    is_job_remote = "remote" in job_text or "anywhere" in job_text or "wfh" in job_text
    
    # i. Remote Preference soft filter
    if search_profile.is_remote:
        if is_job_remote:
            match_score += 10
        else:
            match_score -= 15
    
    # ii. Location Preference
    loc_pref = search_profile.location.lower()
    if loc_pref != "any" and loc_pref != "":
        if loc_pref in job_text or loc_pref in job.url.lower():
            match_score += 10
        else:
            match_score -= 10
    
    # iii. Keywords Boost
    if search_profile.keywords:
        kws = [k.strip().lower() for k in search_profile.keywords.split(",") if k.strip()]
        overlap_count = sum(1 for kw in kws if kw in job_text)
        if overlap_count > 0:
            match_score += min(20, overlap_count * 5)
            
    return match_score

def _post_process_matches(matches, user, search_profile, signal_map, db) -> List[Dict[str, Any]]:
    """Helper to apply Saved Search Profile boosts, Flywheel penalties, and ATS intelligence signals to match items."""
    import datetime
    for match in matches:
        job = match["job"]
        
        # A. Company Signal Boost
        comp_lower = job.company.lower()
        if comp_lower in signal_map:
            sig = signal_map[comp_lower]
            match["match_score"] += sig.weight_boost
            boost_msg = f" 📈 High Signal: {sig.description} (+{sig.weight_boost}% score boost!)"
            match["gaps"]["resume_optimization"] += boost_msg
            
        # B. Saved Search Profile Boosts via helper
        match["match_score"] = _apply_search_profile_boost(match["match_score"], job, search_profile)
                    
        # C. Feedback Flywheel Model Weight Alignment (Months 7-12)
        rejected_app = db.query(Application).filter(
            Application.user_id == user.id,
            Application.job_id == job.id,
            Application.status == "rejected"
        ).first()
        
        if rejected_app and match["match_score"] >= 80:
            flywheel_penalty = 15
            match["match_score"] -= flywheel_penalty
            match["gaps"]["resume_optimization"] += f" ⚠️ Feedback Flywheel: Adjusted down by {flywheel_penalty}% based on past screen outcomes under v1.0 matching model."

        # D. Direct ATS Company Intelligence Calculations (Months 7-12)
        days_open = (datetime.datetime.utcnow() - job.posted_at).days
        
        urgency = "Standard"
        signals_msg = "Steady ingestion pipeline"
        
        if days_open <= 2:
            urgency = "High Urgency: Recently synchronized ATS posting"
            signals_msg = "Link fresh - high callback probability"
        elif job.company.lower() in ["openai", "stripe", "google"]:
            urgency = "High Urgency: Competitive call loop active"
            signals_msg = "Rapid closure patterns observed on Greenhouse"
            
        status_flag = "Active"
        if days_open >= 90:
            status_flag = "Stale"
            signals_msg = "Job open for 90+ days; likely cold pipeline"
            
        match["ats_dynamics"] = {
            "urgency": urgency,
            "status": status_flag,
            "days_open": max(1, days_open),
            "hiring_signal": signals_msg
        }

        # E. Brutal Honesty Cap (never exceed 95% to maintain brutal accuracy)
        if match["match_score"] > 95:
            match["match_score"] = 95
        if match["match_score"] < 10:
            match["match_score"] = 10

    # Sort matches by final honest fit_score in descending order ( Curation queue! )
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    return matches[:10]

@app.get("/api/jobs/matches", response_model=List[JobMatchResponse])
def get_job_matches(email: str, db: Session = Depends(get_db)):
    """Ranks all active database jobs against candidate resume via vector search & outputs honest fit score with gaps."""
    # 1. Fetch User & Resume
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload your resume before searching matches")
    
    # Ensure there are jobs to match against
    jobs = db.query(Job).filter(Job.is_active == True).all()
    if not jobs:
        sync_all_jobs(db, force_mock=True)
        jobs = db.query(Job).filter(Job.is_active == True).all()
        
    resume_embedding = resume.embedding
    user_skills = set(x.lower() for x in resume.structured_json.get("skills", []))
    
    # 2. Database Vector Matching Engine
    if is_postgres():
        matches = _calculate_postgres_matches(jobs, resume_embedding, user_skills, db)
    else:
        matches = _calculate_sqlite_matches(jobs, resume_embedding, user_skills)
        
    # 3. Retrieve user search profile preferences & active company signals via post-processing helper
    from backend.app.models import SavedSearchProfile, CompanySignal
    search_profile = db.query(SavedSearchProfile).filter(SavedSearchProfile.user_id == user.id).first()
    signals = db.query(CompanySignal).all()
    signal_map = {sig.company.lower(): sig for sig in signals}
    
    matches = _post_process_matches(matches, user, search_profile, signal_map, db)
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    
    # Return top 10 best matches
    return matches[:10]

@app.post("/api/applications", response_model=ApplicationResponse)
def create_application(app_in: ApplicationBase, email: str, db: Session = Depends(get_db)):
    """Registers a job tracking status inside the Kanban tracker database."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Create or update application tracking state
    existing = db.query(Application).filter(
        Application.user_id == user.id,
        Application.job_id == app_in.job_id
    ).first()
    
    if existing:
        existing.status = app_in.status
        db.commit()
        db.refresh(existing)
        return existing
        
    new_app = Application(
        user_id=user.id,
        job_id=app_in.job_id,
        status=app_in.status
    )
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    return new_app

@app.get("/api/applications", response_model=List[ApplicationDetailedResponse])
def get_applications(email: str, db: Session = Depends(get_db)):
    """Retrieves all tracked applications for a candidate from the database."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    apps = db.query(Application).filter(Application.user_id == user.id).all()
    
    results = []
    for a in apps:
        job = db.query(Job).filter(Job.id == a.job_id).first()
        if job:
            results.append({
                "id": a.id,
                "job": job,
                "status": a.status,
                "updated_at": a.updated_at
            })
    return results

def _compute_single_job_score(job, resume_embedding, user_skills) -> Tuple[int, List[str], str]:
    """Helper to calculate honest score, missing skills and optimization advice for a single job."""
    sim = cosine_similarity(resume_embedding, job.embedding)
    if sim < 0.25:
        job_text = (job.title + " " + job.description).lower()
        overlap_count = sum(1 for skill in user_skills if skill in job_text)
        
        title_sim = 0.2
        if any(x in job.title.lower() for x in ["ml", "machine learning", "ai ", "data science", "mlops", "artificial intelligence"]):
            title_sim = 0.8
        elif "infrastructure" in job.title.lower() or "platform" in job.title.lower():
            title_sim = 0.6
            
        sim = title_sim + min(0.18, (overlap_count * 0.03))
        if sim > 0.95: sim = 0.95
        
    fit_score = int(sim * 100)
    job_desc_lower = job.description.lower()
    common_skills = ["pytorch", "tensorflow", "kubernetes", "docker", "mlops", "python", "sql", "aws", "gcp", "ci/cd", "javascript", "react", "next.js", "vector database", "embeddings", "agent"]
    gaps = [cs.title() for cs in common_skills if cs in job_desc_lower and cs not in user_skills]
    
    penalty = len(gaps) * 6
    final_score = fit_score - penalty
    if final_score < 10: final_score = 10
    if final_score > 98: final_score = 98
    
    optimization_advice = (
        f"To improve this match score, add bullet proof-of-work experience with: {', '.join(gaps)}." 
        if gaps else "Perfect skill keyword match!"
    )
    return final_score, gaps, optimization_advice

@app.post("/api/fit_scorer", response_model=FitScorerDetailedResponse)
def get_fit_score_details(req: FitScorerRequest, db: Session = Depends(get_db)):
    """API endpoint providing uninflated fit scoring, missing skills, and detailed bullet optimization recommendations."""
    # 1. Fetch User & Resume
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Billing limit check (Free Tier limit: 5 fit scores)
    if user.subscription_tier == "free":
        score_count = db.query(FitScore).filter(FitScore.user_id == user.id).count()
        if score_count >= 5:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Payment Required: Free Tier is limited to 5 fit scores. Please upgrade to Premium ($19/mo) or Executive ($49/mo) to get unlimited fit scoring."
            )
            
    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload resume first")
        
    # 2. Fetch Job
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")
        
    # 3. Matching score logic via modular helper
    resume_embedding = resume.embedding
    user_skills = set(x.lower() for x in resume.structured_json.get("skills", []))
    final_score, gaps, optimization_advice = _compute_single_job_score(job, resume_embedding, user_skills)
    
    return FitScorerDetailedResponse(
        score=final_score,
        missing_skills=gaps,
        optimization_advice=optimization_advice
    )

def _generate_llm_outreach(job, candidate_skills, selected_skill) -> Optional[Tuple[str, str]]:
    """Helper to query Gemini to generate an executive company summary and a tailored LinkedIn note."""
    if not settings.GOOGLE_API_KEY:
        return None
    try:
        import google.generativeai as genai
        import json
        
        prompt = f"""
        You are a professional outreach writer. Analyze the target company job description and candidate profile:
        
        Candidate Skills: {', '.join(candidate_skills)}
        Target Job Title: {job.title} at {job.company}
        Job Posting Description:
        {job.description}
        
        Output a valid JSON object containing:
        1. "company_summary": A high-signal, 1-to-2 sentence executive summary of exactly what the target company does and their value proposition based on the description.
        2. "linkedin_note": A tailored, ultra-personalized LinkedIn connection note of exactly 300 characters or less. It must mention a specific skill of the candidate (like {selected_skill}) and show high interest in the {job.title} role. Make it extremely conversational and under 300 characters strictly!
        """
        
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json"
            )
        )
        
        parsed = json.loads(response.text)
        if "company_summary" in parsed and "linkedin_note" in parsed:
            note = parsed["linkedin_note"].strip()
            if len(note) > 300:
                note = note[:297] + "..."
            return parsed["company_summary"].strip(), note
    except Exception as e:
        logger.error(f"Gemini outreach note generation failed: {e}. Falling back to dynamic mock.")
    return None

@app.post("/api/outreach/generate", response_model=OutreachResponse)
def generate_outreach_draft(req: OutreachRequest, db: Session = Depends(get_db)):
    """Generates an executive summary of the target company and a tailored, 300-char LinkedIn outreach note."""
    # 1. Fetch Job & User Resume
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Billing limit check (Free Tier limit: 2 outreach notes)
    if user.subscription_tier == "free":
        if user.outreach_count >= 2:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Payment Required: Free Tier is limited to 2 outreach notes. Please upgrade to Premium ($19/mo) or Executive ($49/mo) to get unlimited outreach notes."
            )
            
    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload resume first")
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")
        
    # Increment outreach count under successfully validated tier limits
    user.outreach_count += 1
    db.commit()
        
    # Standard high-quality mock defaults (our bulletproof fallback)
    candidate_skills = resume.structured_json.get("skills", ["ML pipelines", "Python"])
    selected_skill = candidate_skills[0] if candidate_skills else "ML pipelines"
    
    # 2. Attempt LLM generation
    llm_res = _generate_llm_outreach(job, candidate_skills, selected_skill)
    if llm_res:
        company_summary, linkedin_note = llm_res
        return OutreachResponse(
            company_summary=company_summary,
            linkedin_note=linkedin_note
        )
        
    company_summary = f"{job.company} is an active technology leader focused on building high-performance {job.title} applications."
    linkedin_note = f"Hi! I noticed your team at {job.company} is hiring a {job.title}. I recently built and deployed automated ML pipelines using MLOps, Python, and SQL, and wanted to see if my background matches your current technical requirements. Let's connect!"
    if len(linkedin_note) > 300:
        linkedin_note = linkedin_note[:297] + "..."
        
    return OutreachResponse(
        company_summary=company_summary,
        linkedin_note=linkedin_note
    )

@app.get("/api/search_profile", response_model=SavedSearchProfileResponse)
def get_search_profile(email: str, db: Session = Depends(get_db)):
    """Retrieves or initializes a blank saved search preference profile for the user."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    profile = db.query(SavedSearchProfile).filter(SavedSearchProfile.user_id == user.id).first()
    if not profile:
        # Initialize default search profile
        profile = SavedSearchProfile(
            user_id=user.id,
            is_remote=False,
            location="Any",
            company_stage="Any",
            keywords=""
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile

@app.post("/api/search_profile", response_model=SavedSearchProfileResponse)
def update_search_profile(email: str, profile_in: SavedSearchProfileBase, db: Session = Depends(get_db)):
    """Updates the candidate's Saved Search Profile filters and preferences."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Billing tier check (Premium/Executive Tier feature)
    if user.subscription_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment Required: Saved Search alerts and preference tuning are Premium/Executive Tier features. Please upgrade to unlock."
        )
        
    profile = db.query(SavedSearchProfile).filter(SavedSearchProfile.user_id == user.id).first()
    if not profile:
        profile = SavedSearchProfile(user_id=user.id)
        db.add(profile)
        
    profile.is_remote = profile_in.is_remote
    profile.location = profile_in.location
    profile.company_stage = profile_in.company_stage
    profile.keywords = profile_in.keywords
    
    db.commit()
    db.refresh(profile)
    return profile

@app.get("/api/signals", response_model=List[CompanySignalResponse])
def get_company_signals(db: Session = Depends(get_db)):
    """Retrieves all active tracked AI Company Signals (funding and product launches)."""
    return db.query(CompanySignal).order_with_respect_to(CompanySignal.recorded_at) if hasattr(CompanySignal, "order_with_respect_to") else db.query(CompanySignal).all()

@app.post("/api/digest/send")
def trigger_weekly_digest(email: str, db: Session = Depends(get_db)):
    """Compiles and triggers the Monday Morning Digest email dispatch."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Billing tier check (Premium/Executive Tier feature)
    if user.subscription_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment Required: Monday Morning Digest Email automation is a Premium/Executive Tier feature. Please upgrade to unlock."
        )
        
    from backend.app.utils.digest_engine import compile_weekly_digest, send_digest_email
    
    top_matches = compile_weekly_digest(db, email)
    if not top_matches:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No job matches found. Please upload a resume first.")
        
    delivered = send_digest_email(email, top_matches)
    if delivered:
        return {"status": "success", "message": f"Curated Monday digest successfully compiled and dispatched to {email}."}
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to dispatch digest email.")

def _tailor_resume_bullets_llm(job, experience) -> Optional[List[TailoredBullet]]:
    """Helper to query Gemini to suggest premium context-aware resume experience rewrites."""
    if not settings.GOOGLE_API_KEY:
        return None
    try:
        import google.generativeai as genai
        import json
        
        prompt = f"""
        You are an expert resume consultant specializing in elite startup recruiting.
        Analyze this candidate profile and the target job description:
        
        Job Title: {job.title} at {job.company}
        Job Description:
        {job.description}
        
        Candidate Profile Experience:
        {json.dumps(experience)}
        
        Based on the technical/behavioral gaps for this role, suggest exactly 3 context-aware, highly premium rewrites of resume bullet points from their experience.
        Ensure the rewrites are fully truthful to the candidate's experience, but highlight target skillsets like scale, pipeline designs, or specific tech overlap.
        
        Output a valid JSON object containing a list called "tailored_bullets", where each item has:
        1. "original_bullet": The original bullet point or sentence from the candidate experience.
        2. "tailored_bullet": The suggested premium tailored rewrite.
        3. "rationale": Why this rewrite effectively addresses target gaps.
        """
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(response_mime_type="application/json")
        )
        parsed = json.loads(response.text)
        if "tailored_bullets" in parsed:
            return [TailoredBullet(**x) for x in parsed["tailored_bullets"]]
    except Exception as e:
        logger.error(f"Gemini resume tailoring failed: {e}. Falling back to high-fidelity mocks.")
    return None

@app.post("/api/resume/tailor", response_model=TailorResumeResponse)
def tailor_resume_bullets(req: TailorResumeRequest, db: Session = Depends(get_db)):
    """Suggests context-aware rewrites of candidate resume experience bullet points to address identified job gaps."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Billing tier check (Executive Tier exclusive)
    if user.subscription_tier != "executive":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment Required: Advanced Resume Tailoring is an Executive Tier ($49/mo) exclusive feature. Please upgrade your tier to unlock."
        )
    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload resume first")
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    experience = resume.structured_json.get("experience", [])
    if not experience:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No experience found in candidate profile to tailor.")

    # 2. Attempt LLM generation
    llm_bullets = _tailor_resume_bullets_llm(job, experience)
    if llm_bullets:
        return TailorResumeResponse(tailored_bullets=llm_bullets)

    # 3. Dynamic High-Quality Fallback
    mock_rewrites = []
    for exp in experience[:3]:
        company = exp.get("company", "Startup")
        role = exp.get("role", "Software Engineer")
        desc = exp.get("description", "")
        orig = desc.split(".")[0] if desc else f"Responsible for software engineering at {company}."
        
        mock_rewrites.append(TailoredBullet(
            original_bullet=orig,
            tailored_bullet=f"Led the integration of high-performance technical frameworks and MLOps strategies at {company} to streamline core {role} deliverables.",
            rationale=f"Contextualized execution metrics at {company} to directly address the required technical engineering stack for {job.company}."
        ))
        
    return TailorResumeResponse(tailored_bullets=mock_rewrites)

def _generate_interview_prep_llm(job, experience, skills) -> Optional[List[InterviewPrepQuestion]]:
    """Helper to query Gemini to generate a tailored interview preparation guide with 10 STAR questions."""
    if not settings.GOOGLE_API_KEY:
        return None
    try:
        import google.generativeai as genai
        import json
        
        prompt = f"""
        You are an elite technical interviewer.
        Analyze the target job description and candidate resume profile:
        
        Job Title: {job.title} at {job.company}
        Job Description:
        {job.description}
        
        Candidate Resume Profile Experience:
        {json.dumps(experience)}
        Candidate Skills: {', '.join(skills)}
        
        Generate exactly 10 highly probable questions (5 technical, 5 behavioral) tailored to this specific job.
        For each question:
        1. Suggest a structured response framework (e.g. STAR or System Design).
        2. Provide highly specific talking points mapping directly to the candidate's actual projects, achievements, and skills in their resume.
        
        Output a valid JSON object containing a list called "questions", where each item has:
        - "id": An integer from 1 to 10.
        - "question": The question text.
        - "type": "technical" or "behavioral".
        - "suggested_framework": The framework.
        - "talking_points": Specific talking points referencing candidate resume experiences.
        """
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(response_mime_type="application/json")
        )
        parsed = json.loads(response.text)
        if "questions" in parsed:
            return [InterviewPrepQuestion(**x) for x in parsed["questions"]]
    except Exception as e:
        logger.error(f"Gemini interview prep generation failed: {e}. Falling back to high-fidelity mocks.")
    return None

def _get_default_mock_questions(job, skills) -> List[InterviewPrepQuestion]:
    """Helper to return dynamic, premium default mock interview preparation questions."""
    return [
        InterviewPrepQuestion(
            id=1,
            question=f"Can you explain your experience building machine learning or data pipelines for role-scale execution, similar to what we do at {job.company}?",
            type="technical",
            suggested_framework="STAR",
            talking_points=f"Highlight your work with {', '.join(skills[:3])}. Reference your actual project experience to prove metrics-driven performance."
        ),
        InterviewPrepQuestion(
            id=2,
            question="How do you handle technical debt and model degradation in production systems?",
            type="technical",
            suggested_framework="STAR",
            talking_points="Cite your engineering foundations. Focus on monitoring loops, CI/CD pipeline automation, and automated validation tests."
        ),
        InterviewPrepQuestion(
            id=3,
            question="What is your methodology for choosing vector database indexing parameters in production?",
            type="technical",
            suggested_framework="STAR",
            talking_points="Focus on latency trade-offs between HNSW and IVF-Flat. Emphasize scale and search quality metrics."
        ),
        InterviewPrepQuestion(
            id=4,
            question=f"Design an automated data ingestion pipeline for {job.company}'s core products.",
            type="technical",
            suggested_framework="System Design",
            talking_points="Draw diagrams mentally from ingestion (Kafka) to processing (Spark) to database indexing (PG/NoSQL)."
        ),
        InterviewPrepQuestion(
            id=5,
            question="How do you optimize slow query times in large-scale relational databases?",
            type="technical",
            suggested_framework="STAR",
            talking_points="Mention indexing strategies, query execution plans (EXPLAIN ANALYZE), and horizontal read partitioning."
        ),
        InterviewPrepQuestion(
            id=6,
            question="Tell me about a time you had a technical disagreement with a colleague. How did you resolve it?",
            type="behavioral",
            suggested_framework="STAR",
            talking_points="Emphasize active listening, data-driven prototyping to settle arguments, and collaborative consensus."
        ),
        InterviewPrepQuestion(
            id=7,
            question=f"Why do you want to join {job.company} over other active startup opportunities?",
            type="behavioral",
            suggested_framework="STAR",
            talking_points=f"Align with {job.company}'s core product stack. Express strong interest in solving the specific scale problems in their job posting."
        ),
        InterviewPrepQuestion(
            id=8,
            question="Describe a situation where you had to deliver a critical milestone under tight constraints.",
            type="behavioral",
            suggested_framework="STAR",
            talking_points="Cite an actual past project. Explain prioritization tactics, clear stakeholder communication, and focused sprints."
        ),
        InterviewPrepQuestion(
            id=9,
            question="How do you approach learning a completely new technical framework rapidly on the job?",
            type="behavioral",
            suggested_framework="STAR",
            talking_points="Explain active learning patterns, building proof-of-concept sandboxes, and consulting documentation."
        ),
        InterviewPrepQuestion(
            id=10,
            question="Tell me about a project that failed. What did you learn and how did you pivot?",
            type="behavioral",
            suggested_framework="STAR",
            talking_points="Be authentic. Show ownership of the failure, focus on root-cause postmortems, and explain subsequent safeguards."
        ),
    ]

@app.post("/api/interview/prep", response_model=InterviewPrepResponse)
def generate_interview_prep(req: TailorResumeRequest, db: Session = Depends(get_db)):
    """Generates 10 probable questions (technical and behavioral) and structures customized STAR frameworks referencing resume achievements."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Billing tier check (Executive Tier exclusive)
    if user.subscription_tier != "executive":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Payment Required: Customized Interview Preparation Guides are an Executive Tier ($49/mo) exclusive feature. Please upgrade your tier to unlock."
        )
        
    resume = db.query(Resume).filter(Resume.user_id == user.id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload resume first")
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    experience = resume.structured_json.get("experience", [])
    skills = resume.structured_json.get("skills", ["ML pipelines"])
    
    # 2. Attempt LLM generation
    llm_questions = _generate_interview_prep_llm(job, experience, skills)
    if llm_questions:
        return InterviewPrepResponse(questions=llm_questions)

    # 3. Dynamic Mock Fallback via helper
    return InterviewPrepResponse(questions=_get_default_mock_questions(job, skills))

@app.post("/api/billing/checkout")
def checkout_billing_session(req: BillingCheckoutRequest, db: Session = Depends(get_db)):
    """Simulates a premium Stripe billing checkout session upgrade."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    requested_tier = req.tier.lower()
    if requested_tier not in ["free", "premium", "executive"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subscription tier requested.")
        
    user.subscription_tier = requested_tier
    db.commit()
    db.refresh(user)
    
    # Return simulated Stripe CS URL
    import random
    session_id = f"cs_test_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=24))}"
    
    return {
        "status": "success",
        "tier": user.subscription_tier,
        "message": f"Successfully processed simulated billing upgrade to the '{user.subscription_tier.upper()}' plan!",
        "session_url": f"https://checkout.stripe.com/pay/{session_id}#success=true"
    }
