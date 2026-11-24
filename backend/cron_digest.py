import logging
import os
import sys

# Resolve project root path dynamically
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.utils.digest_engine import compile_weekly_digest, send_digest_email

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cron.digest")

def run_weekly_digest_cron():
    logger.info("━" * 60)
    logger.info("  🚀 STARTING CRON: WEEKLY MONDAY MORNING DIGEST PIPELINE")
    logger.info("━" * 60)
    
    db = SessionLocal()
    try:
        users = db.query(User).all()
        logger.info(f"Discovered {len(users)} registered candidates to process.")
        
        success_count = 0
        for user in users:
            logger.info(f"Processing candidate: {user.email}...")
            try:
                # 1. Compile Top 5 matches incorporating all signals & profiles
                top_matches = compile_weekly_digest(db, user.email)
                if not top_matches:
                    logger.warning(f"No job matches discovered for {user.email}. Skipping email.")
                    continue
                
                # 2. Transmit formatted email
                dispatched = send_digest_email(user.email, top_matches)
                if dispatched:
                    logger.info(f"✓ Curated Monday digest dispatched to {user.email} successfully!")
                    success_count += 1
            except Exception as e:
                logger.error(f"Error compiling/dispatched digest for {user.email}: {e}")
                
        logger.info("━" * 60)
        logger.info(f"  ✓ CRON COMPLETE! Dispatched {success_count} weekly digests successfully.")
        logger.info("━" * 60)
    finally:
        db.close()

if __name__ == "__main__":
    run_weekly_digest_cron()
