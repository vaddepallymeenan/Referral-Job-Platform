# Outreach Intelligence Job Copilot 🚀

The **Outreach Intelligence Job Copilot** is a premium command-line companion designed to turn your job search into a highly targeted outreach operation. Instead of generic applications, it parses your resume, scores job fits, maps warm alumni connection pathways, ranks contacts, and drafts custom 5-stage outreach sequences tailored to target companies.

---

## 🛠️ Setup & Installation

### 1. Prerequisites
- **Python**: v3.10 or higher.
- **Pipenv / Virtualenv**: Installed and configured.

### 2. Environment Configuration
Create a `.env` file in the project root:
```env
# Brave Search API Key (Optional fallback, can be empty)
BRAVE_API_KEY=your-brave-key

# Candidate Details (Fallback options if resume parsing is mock)
CANDIDATE_NAME="Your Name"
CANDIDATE_INSTITUTE="IIT Kanpur"
CANDIDATE_GRAD_YEAR="2024"
CANDIDATE_SKILLS="ML pipelines, model deployment, MLOps, applied machine learning"
```

### 3. Dependency Installation
Install required packages inside your virtual environment:
```bash
pip install pypdf pandas beautifulsoup4 requests python-dotenv
```

---

## 🚀 CLI Quickstart

The main entry point is `copilot/cli.py`. You can target multiple companies, careers pages, or direct URLs:

```bash
python copilot/cli.py \
  --resume resume.pdf \
  --companies "Sarvam AI, Krutrim, DevRev" \
  --output-dir custom_reports
```

### Supported Parameters:
*   `--resume`: Path to your candidate resume PDF (default: `resume.pdf`).
*   `--companies`: A comma-separated list of company names, job posting URLs, or text descriptions.
*   `--output-dir`: The target folder where the intelligence markdown reports will be saved (default: `output`).

---

## 🏗️ Architecture & Processing Flow

The copilot operates as a side-car module consuming your legacy pipeline engines safely:

```
[Resume PDF + Targets List]
           │
           ▼
   [input_parser.py] ──► Normalizes targets & extracts user profile
           │
           ▼
  [copilot_runner.py] (Pipeline Orchestration)
    ├─► [alumni_expander.py]  ──► Looks up warm alumni (IIT Kanpur, Delhi, Bombay)
    ├─► [contact_ranker.py]   ──► Ranks contacts & generates 'Why They Matter' explanation
    ├─► [legacy.FitScorer]    ──► Conducts technical resume-to-JD fit scoring
    ├─► [referral_engine.py]  ──► Computes referral likelihood & paths
    ├─► [strategy_engine.py]  ──► Determines verdict (PRIORITIZE / APPLY / SKIP)
    └─► [report_generator.py] ──► Assembles beautiful, premium markdown reports
```

---

## 🎯 How to Use the Output Reports

Every run outputs a customized `.md` report for each target company. These contain:
1.  **Job Fit Verdict**: Direct apply / prioritize referral / skip instructions.
2.  **Contact Intelligence**: A ranked list of your best company contacts with structured email addresses, LinkedIn URLs, and their personal relevance.
3.  **Outreach Playbooks**: 5 hyper-targeted message templates customized to the target contact type and hiring event (LinkedIn connection, follow-ups, and cold emails).
