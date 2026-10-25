# workspace_trigger.py
# Google Workspace automation, run by the backend after a match is approved
#
# Does 3 things in sequence:
# 1. Sends an intro email via Gmail API
# 2. Creates a shared Drive folder with a 90-day milestones doc
# 3. Creates a Calendar event with Meet link
#
# ophia-backend/app.py runs trigger_workspace_automation() as a FastAPI BackgroundTask

import os
import base64
import datetime
import html
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Google API libraries
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)

load_dotenv(dotenv_path=os.path.join(repo_root, '.env'))

# ── Config ────────────────────────────────────────────────────────────────────
CREDENTIALS_PATH = os.path.join(repo_root, os.getenv(
    "WORKSPACE_CREDENTIALS_PATH", "./ophia-data/credentials/workspace-credentials.json"
))
TOKEN_PATH = os.path.join(os.path.dirname(CREDENTIALS_PATH), 'token.json')
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
PROGRAMME_TZ = ZoneInfo("Asia/Kuala_Lumpur")

# Scopes — what permissions we're requesting from Google
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
]


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION
# ═══════════════════════════════════════════════════════════════════════════════

def get_google_credentials():
    """
    Handles OAuth 2.0 authentication.
    
    First time: Opens browser for you to log in → saves token.json
    After that: Uses saved token.json automatically (no browser needed)
    
    Returns Google credentials object.
    """
    creds = None

    # Load existing token if it exists
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid credentials, do the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                print(f"[workspace] ❌ credentials file not found at: {CREDENTIALS_PATH}")
                return None

            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            # This opens your browser for login
            creds = flow.run_local_server(port=0)

        # Save the token for next time
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"[workspace] ✅ Saved token to {TOKEN_PATH}")

    return creds


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: SEND INTRODUCTION EMAIL
# ═══════════════════════════════════════════════════════════════════════════════

def send_intro_email(
    creds,
    startup_name: str,
    mentor_name: str,
    recipient_email: str,
    synergy_score: int
) -> bool:
    """
    Sends a professional introduction email via Gmail API.
    
    For the hackathon demo, recipient_email is your own email
    (so you can show the judges the real email arriving in inbox).
    
    Returns True if sent successfully, False if failed.
    """
    try:
        service = build("gmail", "v1", credentials=creds)

        # Build email content
        subject = f"OPHIA: New Ecosystem Match — {startup_name} × {mentor_name}"
        # Names come from the database — escape them before putting them in HTML
        startup_name, mentor_name = html.escape(startup_name), html.escape(mentor_name)

        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #0b2416; padding: 24px; border-radius: 12px 12px 0 0;">
                <h1 style="color: #2ecc71; font-size: 24px; margin: 0;">OPHIA</h1>
                <p style="color: #a8c4b0; margin: 4px 0 0;">Ecosystem Orchestration Platform</p>
            </div>
            <div style="background: #f8f9f3; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e0e0e0;">
                <h2 style="color: #0b2416;">🤝 New Ecosystem Match Approved</h2>
                <p style="color: #5d6e65;">
                    A new mentorship match has been approved by your programme administrator.
                </p>
                
                <div style="background: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; margin: 16px 0;">
                    <p><strong>Startup:</strong> {startup_name}</p>
                    <p><strong>Mentor:</strong> {mentor_name}</p>
                    <p><strong>AI Synergy Score:</strong> 
                        <span style="color: #2ecc71; font-weight: bold;">{synergy_score}%</span>
                    </p>
                </div>
                
                <h3 style="color: #0b2416;">Your 90-Day Journey Begins Now</h3>
                <ul style="color: #5d6e65;">
                    <li><strong>Day 30:</strong> Establish goals and align on tech stack</li>
                    <li><strong>Day 60:</strong> Mid-term review and progress audit</li>
                    <li><strong>Day 90:</strong> Final evaluation and programme completion</li>
                </ul>
                
                <p style="color: #5d6e65; font-size: 12px; margin-top: 24px;">
                    This match was suggested by OPHIA, an AI mentor-matching tool, and approved
                    by a programme administrator.
                </p>
            </div>
        </div>
        """

        # Build the MIME message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = SENDER_EMAIL
        message["To"] = recipient_email
        message.attach(MIMEText(html_body, "html"))

        # Encode and send
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()

        print(f"[workspace] ✅ Intro email sent to {recipient_email}")
        return True

    except Exception as e:
        print(f"[workspace] ❌ Email failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: CREATE GOOGLE DRIVE FOLDER + DOC
# ═══════════════════════════════════════════════════════════════════════════════

def create_drive_workspace(
    creds,
    startup_name: str,
    mentor_name: str,
    share_with: str = None
) -> str:
    """
    Creates a Google Drive folder and a 90-day milestones Google Doc inside it,
    shared with `share_with` (if given) as an editor. The folder is NOT made
    public — only the owner and the invited person can open it.

    Returns the URL of the created folder (stored in Firestore).
    """
    try:
        service = build("drive", "v3", credentials=creds)
        folder_name = f"OPHIA — {startup_name} × {mentor_name}"

        # Step 2a: Create the folder
        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        folder = service.files().create(
            body=folder_metadata,
            fields="id, webViewLink"
        ).execute()

        folder_id = folder.get("id")
        folder_url = folder.get("webViewLink")
        print(f"[workspace] ✅ Created Drive folder: {folder_name}")

        # Step 2b: Create the 90-day milestones doc inside the folder.
        # Uploading plain text with a Google Doc mimeType makes Drive convert
        # it, so the doc is created WITH the milestone content inside.
        doc_content = get_milestone_doc_content(startup_name, mentor_name)
        doc_metadata = {
            "name": f"90-Day Milestone Plan — {startup_name}",
            "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]
        }
        service.files().create(
            body=doc_metadata,
            media_body=MediaInMemoryUpload(doc_content.encode("utf-8"), mimetype="text/plain"),
            fields="id"
        ).execute()

        print("[workspace] ✅ Created 90-day milestone doc in folder")

        # Step 2c: Share the folder with the participant only
        if share_with:
            service.permissions().create(
                fileId=folder_id,
                body={"type": "user", "role": "writer", "emailAddress": share_with},
                sendNotificationEmail=False,
            ).execute()
            print(f"[workspace] ✅ Shared folder with {share_with}")

        print(f"[workspace] ✅ Drive folder URL: {folder_url}")
        return folder_url

    except Exception as e:
        print(f"[workspace] ❌ Drive creation failed: {e}")
        return None


def get_milestone_doc_content(startup_name: str, mentor_name: str) -> str:
    """
    Returns the content for the 90-day milestone doc.
    Reads from templates/milestone_doc.txt if it exists.
    """
    template_path = os.path.join(script_dir, 'templates', 'milestone_doc.txt')

    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        return template.replace("{startup_name}", startup_name).replace("{mentor_name}", mentor_name)

    # Default template
    return f"""
OPHIA — 90-Day Ecosystem Milestone Plan
Startup: {startup_name}
Mentor: {mentor_name}
Generated by: OPHIA mentor matching

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DAY 30 — Foundation Sprint
Objective: Establish goals, align on tech stack, complete first check-in
[ ] Initial kick-off meeting completed
[ ] 90-day goals documented and agreed upon
[ ] Tech stack review completed
[ ] Communication cadence established

DAY 60 — Mid-Term Review
Objective: Progress audit and course correction
[ ] Mid-term review meeting completed
[ ] Progress against Day 30 goals assessed
[ ] Blockers identified and addressed
[ ] Revised goals for Day 90 confirmed

DAY 90 — Final Evaluation
Objective: Programme completion sign-off
[ ] Final evaluation meeting completed
[ ] Outcomes documented
[ ] Next steps (continued engagement or graduation) confirmed
[ ] Feedback submitted to the programme team

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This document is auto-generated by OPHIA.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: CREATE GOOGLE CALENDAR EVENT + MEET LINK
# ═══════════════════════════════════════════════════════════════════════════════

def create_calendar_event(
    creds,
    startup_name: str,
    mentor_name: str,
    attendee_email: str
) -> str:
    """
    Creates a Google Calendar kick-off event with a Google Meet link.
    
    Returns the Calendar event ID.
    """
    try:
        service = build("calendar", "v3", credentials=creds)

        # Schedule the kick-off for 3 days from now at 10am Kuala Lumpur time
        now = datetime.datetime.now(PROGRAMME_TZ)
        start_time = now + datetime.timedelta(days=3)
        start_time = start_time.replace(hour=10, minute=0, second=0, microsecond=0)
        end_time = start_time + datetime.timedelta(hours=1)

        event = {
            "summary": f"OPHIA Kick-off: {startup_name} × {mentor_name}",
            "description": (
                f"Welcome to your 90-day OPHIA mentorship programme!\n\n"
                f"Startup: {startup_name}\n"
                f"Mentor: {mentor_name}\n\n"
                f"This kick-off is the start of your structured 90-day journey. "
                f"Please come prepared to discuss your goals and challenges."
            ),
            # isoformat() includes the +08:00 offset, so 10:00 means 10am KL
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Asia/Kuala_Lumpur"
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Asia/Kuala_Lumpur"
            },
            "attendees": [
                {"email": attendee_email}
            ],
            # This tells Google to auto-generate a Meet link
            "conferenceData": {
                "createRequest": {
                    # Must be unique per request, or re-approving a pair reuses the old Meet
                    "requestId": f"ophia-{uuid.uuid4().hex}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"}
                }
            }
        }

        created_event = service.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all"    # Sends email invites to attendees
        ).execute()

        event_id = created_event.get("id")
        meet_link = (
            created_event.get("conferenceData", {})
            .get("entryPoints", [{}])[0]
            .get("uri", "No Meet link")
        )

        print(f"[workspace] ✅ Calendar event created: {created_event.get('summary')}")
        print(f"[workspace] ✅ Google Meet link: {meet_link}")
        return event_id

    except Exception as e:
        print(f"[workspace] ❌ Calendar event failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# MASTER TRIGGER
# ═══════════════════════════════════════════════════════════════════════════════

def trigger_workspace_automation(
    startup_name: str,
    mentor_name: str,
    synergy_score: int,
    contact_email: str = None
) -> dict:
    """
    Entry point, run by the backend as a background task.
    
    Runs all 3 workspace automations in sequence:
    1. Send intro email
    2. Create Drive folder + milestone doc
    3. Create Calendar event with Meet link
    
    Returns a dict with all the created resource URLs/IDs.
    
    """
    print(f"\n[workspace] 🚀 Starting workspace automation for: {startup_name} × {mentor_name}")

    result = {
        "startup_name": startup_name,
        "mentor_name": mentor_name,
        "email_sent": False,
        "drive_folder_url": None,
        "calendar_event_id": None,
        "errors": []
    }

    # Use sender email as contact if none provided (good enough for demo)
    if not contact_email:
        contact_email = SENDER_EMAIL

    # Get credentials (first time opens browser, after that uses token.json)
    creds = get_google_credentials()

    if not creds:
        result["errors"].append("Failed to get Google credentials")
        print("[workspace] ❌ Could not get Google credentials. Check setup.")
        return result

    # ── Step 1: Send email ────────────────────────────────────────────────────
    email_sent = send_intro_email(
        creds,
        startup_name=startup_name,
        mentor_name=mentor_name,
        recipient_email=contact_email,
        synergy_score=synergy_score
    )
    result["email_sent"] = email_sent

    # ── Step 2: Create Drive workspace ────────────────────────────────────────
    folder_url = create_drive_workspace(
        creds,
        startup_name=startup_name,
        mentor_name=mentor_name,
        share_with=contact_email if contact_email != SENDER_EMAIL else None
    )
    result["drive_folder_url"] = folder_url

    # ── Step 3: Create Calendar event ────────────────────────────────────────
    event_id = create_calendar_event(
        creds,
        startup_name=startup_name,
        mentor_name=mentor_name,
        attendee_email=contact_email
    )
    result["calendar_event_id"] = event_id

    # Each step logs its own exception; record which ones failed for the backend
    for ok, step in ((email_sent, "intro email"), (folder_url, "Drive folder"), (event_id, "Calendar kick-off")):
        if not ok:
            result["errors"].append(f"{step} failed (see server log)")

    print(f"[workspace] ✅ Automation complete for {startup_name} × {mentor_name}")
    print(f"[workspace] Result: {result}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# RUN DIRECTLY FOR TESTING
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    # Emoji in log lines would crash print() on a cp1252 Windows console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== Testing workspace_trigger.py ===")
    print("This will open your browser for Google login on first run.")
    print()

    result = trigger_workspace_automation(
        startup_name="DataShield",
        mentor_name="Ehtisham Raza",
        synergy_score=96,
        contact_email=SENDER_EMAIL
    )

    print("\n=== RESULT ===")
    print(f"Email sent:      {result['email_sent']}")
    print(f"Drive folder:    {result['drive_folder_url']}")
    print(f"Calendar event:  {result['calendar_event_id']}")
    print(f"Errors:          {result['errors']}")