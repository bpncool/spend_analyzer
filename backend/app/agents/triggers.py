import os
import shutil
import asyncio
from sqlalchemy.orm import Session
from .orchestrator import orchestrate_statement_processing

# Define directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # backend/
STATEMENTS_DIR = os.path.join(BASE_DIR, "statements_to_process")
EMAIL_INBOX_DIR = os.path.join(BASE_DIR, "email_inbox")

# Create directories on load
os.makedirs(STATEMENTS_DIR, exist_ok=True)
os.makedirs(EMAIL_INBOX_DIR, exist_ok=True)

# Ensure gitkeep exists so git tracks these folders
for d in (STATEMENTS_DIR, EMAIL_INBOX_DIR):
    gitkeep = os.path.join(d, ".gitkeep")
    if not os.path.exists(gitkeep):
        try:
            with open(gitkeep, "w") as f:
                f.write("")
        except Exception:
            pass

async def scan_folder_manually(db: Session = None) -> int:
    """Manually scans the statements_to_process folder and triggers the pipeline for any files found.
    Returns:
        The number of files processed.
    """
    files = [
        f for f in os.listdir(STATEMENTS_DIR)
        if f.lower().endswith((".pdf", ".txt", ".csv"))
    ]
    
    processed_count = 0
    for filename in files:
        file_path = os.path.join(STATEMENTS_DIR, filename)
        # Process in the background or await
        status = await orchestrate_statement_processing(file_path, "folder_trigger")
        if status in ("completed", "failed", "human_required"):
            processed_count += 1
            
    return processed_count

async def scan_emails_manually(db: Session = None) -> int:
    """Manually scans the mock email_inbox folder representing statement attachments.
    Returns:
        The number of email statements processed.
    """
    files = [
        f for f in os.listdir(EMAIL_INBOX_DIR)
        if f.lower().endswith((".pdf", ".txt", ".csv"))
    ]
    
    processed_count = 0
    for filename in files:
        file_path = os.path.join(EMAIL_INBOX_DIR, filename)
        # In a real IMAP check, we would download attachment to a temp file, here we read from mock folder
        status = await orchestrate_statement_processing(file_path, "email_attachment_trigger")
        if status in ("completed", "failed", "human_required"):
            processed_count += 1
            
    return processed_count

# =============================================================================
# Background Trigger Loops
# =============================================================================

async def start_background_triggers_loop():
    """Background task loop that polls directories every 10 seconds for new files.
    This mimics real triggers inside a dev server process.
    """
    print(f"Agentic triggers loop started. Watching folders:\n  - Folder: {STATEMENTS_DIR}\n  - Email Inbox: {EMAIL_INBOX_DIR}")
    while True:
        try:
            # Check folder
            await scan_folder_manually()
            
            # Check mock email inbox
            await scan_emails_manually()
            
        except Exception as e:
            print(f"Error in background triggers loop: {e}")
            
        await asyncio.sleep(10)
