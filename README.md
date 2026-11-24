# Referral-First Job Platform

A SaaS-style job search platform: resume parsing, job matching, honest fit scoring, AI resume tailoring and referral-focused outreach — built around warm intros instead of cold applications.

## Features
- **FastAPI backend** — users, resume upload/parse, job sync, matches, applications, fit scorer, outreach generation, resume tailoring, interview prep, weekly digest, billing stub
- **Outreach Copilot (CLI)** — company strategy, alumni pathway mapping, contact ranking, referral-likelihood scoring and 5-stage outreach sequences → markdown reports ([copilot/](copilot/))
- **Next.js dashboard** — frontend for jobs, matches and applications
- **Audits** — automated security + code-quality audit scripts with reports in [docs/](docs/)

## Tech
Python · FastAPI · SQLAlchemy (SQLite / Postgres + pgvector) · Next.js + TypeScript + Tailwind · Brave / Hunter APIs · LLMs (Groq / Claude / Ollama)

## Run
```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.app.main:app --reload          # API at :8000/docs
cd frontend && npm install && npm run dev      # UI at :3000
python -m copilot.cli --help                   # outreach copilot
```

## Structure
```
backend/    FastAPI app, models, digest engine, resume parser
copilot/    outreach intelligence CLI
frontend/   Next.js dashboard
legacy/     original pipeline scripts (see Job-Hunter repo)
audit/      security + code-quality audit tooling
docs/       roadmap, plans, audit reports
```
