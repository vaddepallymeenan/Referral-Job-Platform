import os
import sys
import argparse
from pathlib import Path

# Ensure project root is in sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load env variables before other imports
try:
    from dotenv import load_dotenv
    load_dotenv(Path(project_root) / ".env")
except ImportError:
    pass
os.environ["BRAVE_API_KEY"] = ""

from copilot.input_parser import parse_input
from copilot.copilot_runner import CopilotRunner

def main():
    parser = argparse.ArgumentParser(description="Outreach Intelligence Job Copilot — CLI Entry")
    parser.add_argument(
        "--resume",
        type=str,
        default=os.environ.get("RESUME_PDF_PATH", "resume.pdf"),
        help="Path to the candidate's resume PDF file."
    )
    parser.add_argument(
        "--companies",
        type=str,
        required=True,
        help="Comma-separated list of company names, job URLs, or description strings."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Target directory where generated outreach markdown reports will be saved."
    )

    args = parser.parse_args()

    resume_path = args.resume
    if not os.path.isabs(resume_path):
        resume_path = os.path.abspath(os.path.join(project_root, resume_path))

    # Parse targets raw list
    targets_raw = [item.strip() for item in args.companies.split(",") if item.strip()]

    print(f"📄 Resume path: {resume_path}")
    print(f"🏢 Targets raw: {targets_raw}")
    print(f"📁 Output directory: {args.output_dir}")

    try:
        # 1. Parse Input
        print("\n[Step 1] Parsing inputs and resume...")
        request = parse_input(resume_path, targets_raw)
        print(f"✅ User profile parsed: {request.user_profile.name} ({request.user_profile.college})")
        print(f"🎓 Skills detected: {request.user_profile.skills[:5]}...")

        # 2. Run Pipeline
        print("\n[Step 2] Launching Copilot Runner...")
        runner = CopilotRunner(output_dir=args.output_dir)
        results = runner.run(request)

        print("\n==================================================")
        print("🎉 Processing complete! Reports saved to project root /output/")
        for r in results:
            print(f"- {r['company_name']}: Fit Score = {r['fit_score'].overall_score}/10 | {r['report_path']}")
        print("==================================================")

    except Exception as e:
        print(f"\n❌ Error executing copilot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
