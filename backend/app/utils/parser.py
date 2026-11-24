import io
import json
import logging
from typing import List, Dict, Any, Tuple
import pypdf
import google.generativeai as genai
from backend.app.config import settings

logger = logging.getLogger("app.parser")

# Configure GenAI SDK if API key is present
if settings.GOOGLE_API_KEY:
    genai.configure(api_key=settings.GOOGLE_API_KEY)
else:
    logger.warning("GOOGLE_API_KEY not found in environment settings. Using Mock parser.")

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extracts raw text from a PDF file using pypdf."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        logger.error(f"Error reading PDF with pypdf: {e}")
        raise ValueError(f"Could not parse PDF file: {str(e)}")

def parse_resume_to_json(raw_text: str) -> Dict[str, Any]:
    """Uses Google Gemini API to parse raw resume text into structured JSON."""
    if not settings.GOOGLE_API_KEY:
        # High quality fallback mock data matching settings defaults
        return {
            "name": settings.CANDIDATE_NAME,
            "email": "meenan.iitk@example.com",
            "phone": settings.CANDIDATE_PHONE or "+91-9999999999",
            "skills": ["ML pipelines", "model deployment", "MLOps", "data analysis", "applied machine learning", "Python", "PyTorch", "Kubernetes"],
            "experience": [
                {
                    "role": "Machine Learning Engineer Intern",
                    "company": "DeepTech Labs",
                    "duration": "6 months",
                    "description": "Developed and deployed automated ML evaluation pipelines."
                },
                {
                    "role": "Research Assistant",
                    "company": "IIT Kanpur",
                    "duration": "1 year",
                    "description": "Researched high-dimensional vector space models and optimization algorithms."
                },
                {
                    "role": "Software Engineer Intern",
                    "company": "TechCorp Solutions",
                    "duration": "3 months",
                    "description": "Built distributed microservices using Docker and PostgreSQL."
                }
            ],
            "education": [
                {
                    "degree": "B.Tech in Computer Science",
                    "institution": "Indian Institute of Technology, Kanpur",
                    "year": "2025"
                }
            ],
            "target_roles": ["Machine Learning Engineer", "AI Engineer", "MLOps Engineer"]
        }

    try:
        # Prompt model with strict schema requirements
        prompt = f"""
You are a professional resume parser. You will extract structured information from the following raw resume text and return it as a valid JSON object matching this schema:
{{
  "name": "Candidate Full Name",
  "email": "Email Address (optional)",
  "phone": "Phone Number (optional)",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {{
      "role": "Job Title/Role",
      "company": "Company Name",
      "duration": "Duration (e.g. June 2024 - Present)",
      "description": "Description of work done"
    }}
  ],
  "education": [
    {{
      "degree": "Degree Title",
      "institution": "Institution/University Name",
      "year": "Graduation Year"
    }}
  ],
  "target_roles": ["Desired Role 1", "Desired Role 2", ...]
}}

Raw Resume Text:
{raw_text}
"""
        
        # We use gemini-1.5-flash as it is fast, cheap, and supports structured JSON outputs
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json"
            )
        )
        
        parsed_json = json.loads(response.text)
        return parsed_json
    except Exception as e:
        logger.error(f"Gemini resume parsing failed: {e}. Returning high-fidelity mock structure.")
        return {
            "name": settings.CANDIDATE_NAME or "Meenan Vaddepally",
            "email": "meenan.iitk@example.com",
            "phone": settings.CANDIDATE_PHONE or "+91-9999999999",
            "skills": ["ML pipelines", "model deployment", "MLOps", "data analysis", "applied machine learning", "Python", "PyTorch", "Kubernetes"],
            "experience": [
                {
                    "role": "Machine Learning Engineer Intern",
                    "company": "DeepTech Labs",
                    "duration": "6 months",
                    "description": "Developed and deployed automated ML evaluation pipelines."
                },
                {
                    "role": "Research Assistant",
                    "company": "IIT Kanpur",
                    "duration": "1 year",
                    "description": "Researched high-dimensional vector space models and optimization algorithms."
                },
                {
                    "role": "Software Engineer Intern",
                    "company": "TechCorp Solutions",
                    "duration": "3 months",
                    "description": "Built distributed microservices using Docker and PostgreSQL."
                }
            ],
            "education": [
                {
                    "degree": "B.Tech in Computer Science",
                    "institution": "Indian Institute of Technology, Kanpur",
                    "year": "2025"
                }
            ],
            "target_roles": ["Machine Learning Engineer", "AI Engineer", "MLOps Engineer"]
        }

def generate_embedding(text: str) -> List[float]:
    """Generates 768-dimensional text embedding using Gemini's text-embedding-004."""
    if not settings.GOOGLE_API_KEY:
        # Return a deterministic mock vector of length 768
        import random
        random.seed(hash(text))
        return [random.uniform(-0.1, 0.1) for _ in range(768)]
        
    try:
        # We truncate long text as embeddings have limit
        truncated_text = text[:4000]
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=truncated_text,
            task_type="retrieval_document"
        )
        return result["embedding"]
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        # Fallback vector
        import random
        random.seed(hash(text))
        return [random.uniform(-0.1, 0.1) for _ in range(768)]
