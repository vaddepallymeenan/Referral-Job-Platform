from pydantic import BaseModel, EmailStr, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: str
    subscription_tier: str
    outreach_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class ResumeStructured(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: List[str]
    experience: List[Dict[str, Any]]
    education: List[Dict[str, Any]]
    target_roles: List[str]

class ResumeResponse(BaseModel):
    user_id: str
    raw_text: str
    structured_json: ResumeStructured
    updated_at: datetime
    
    class Config:
        from_attributes = True

class JobBase(BaseModel):
    company: str
    title: str
    description: str
    url: str
    source: str
    ats_type: str

class JobResponse(JobBase):
    id: str
    posted_at: datetime
    last_seen_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True

class FitScoreResponse(BaseModel):
    user_id: str
    job_id: str
    score: int
    gaps_json: Dict[str, Any]
    scored_at: datetime
    model_version: str
    
    class Config:
        from_attributes = True

class JobMatchResponse(BaseModel):
    job: JobResponse
    match_score: int
    distance: float
    gaps: Dict[str, Any]
    ats_dynamics: Optional[Dict[str, Any]] = None

class ApplicationBase(BaseModel):
    job_id: str
    status: str

class ApplicationResponse(ApplicationBase):
    id: str
    user_id: str
    applied_at: Optional[datetime] = None
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ApplicationDetailedResponse(BaseModel):
    id: str
    job: JobResponse
    status: str
    updated_at: datetime
    
    class Config:
        from_attributes = True

class FitScorerRequest(BaseModel):
    email: str
    job_id: str

class FitScorerDetailedResponse(BaseModel):
    score: int
    missing_skills: List[str]
    optimization_advice: str

class OutreachRequest(BaseModel):
    email: str
    job_id: str

class OutreachResponse(BaseModel):
    company_summary: str
    linkedin_note: str

class SavedSearchProfileBase(BaseModel):
    is_remote: bool
    location: str
    company_stage: str
    keywords: str

class SavedSearchProfileResponse(SavedSearchProfileBase):
    user_id: str
    
    class Config:
        from_attributes = True

class CompanySignalResponse(BaseModel):
    id: str
    company: str
    signal_type: str
    description: Optional[str] = None
    weight_boost: int
    recorded_at: datetime
    
    class Config:
        from_attributes = True

class TailorResumeRequest(BaseModel):
    email: str
    job_id: str

class TailoredBullet(BaseModel):
    original_bullet: str
    tailored_bullet: str
    rationale: str

class TailorResumeResponse(BaseModel):
    tailored_bullets: List[TailoredBullet]

class InterviewPrepQuestion(BaseModel):
    id: int
    question: str
    type: str # technical, behavioral
    suggested_framework: str
    talking_points: str

class InterviewPrepResponse(BaseModel):
    questions: List[InterviewPrepQuestion]

class BillingCheckoutRequest(BaseModel):
    email: str
    tier: str




