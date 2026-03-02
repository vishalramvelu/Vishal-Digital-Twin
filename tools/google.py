"""tools/google.py — Google Calendar API via OAuth"""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv, set_key
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"

CLIENT_ID = os.environ["GOOG_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOG_CLIENT_SECRET"]

_CLIENT_CONFIG = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost:8090"],
    }
}


def _get_credentials():
    """Load OAuth2 credentials from .env or run the consent flow."""
    refresh_token = os.environ.get("GOOG_REFRESH_TOKEN")

    if refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=TOKEN_URI,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    # First run — open browser for consent
    flow = InstalledAppFlow.from_client_config(_CLIENT_CONFIG, SCOPES)
    creds = flow.run_local_server(port=8090)

    # Persist refresh token to .env
    set_key(str(ENV_PATH), "GOOG_REFRESH_TOKEN", creds.refresh_token)
    os.environ["GOOG_REFRESH_TOKEN"] = creds.refresh_token

    return creds


def _get_service():
    return build("calendar", "v3", credentials=_get_credentials())


def _ensure_tz(dt_str: str) -> str:
    """Append 'Z' to an ISO-8601 string if it has no timezone suffix."""
    if re.search(r"[Zz]$|[+-]\d{2}:\d{2}$", dt_str):
        return dt_str
    return dt_str + "Z"


# ── Public helpers called by agent tools ──────────────────────────────


def _list_calendar_events(date_range=None, attendees=None, keyword=None):
    """List Google Calendar events with optional filters.

    Args:
        date_range: (start, end) ISO-8601 datetime strings. Defaults to next 7 days.
        attendees: Email addresses to filter by (client-side).
        keyword: Free-text search term passed to the Calendar API ``q`` param.

    Returns:
        List of event dicts (max 25, ordered by start time).
    """
    service = _get_service()

    params = {
        "calendarId": "primary",
        "maxResults": 25,
        "singleEvents": True,
        "orderBy": "startTime",
    }

    if date_range:
        start, end = date_range
        if start:
            params["timeMin"] = _ensure_tz(
                start if "T" in start else start + "T00:00:00Z"
            )
        if end:
            params["timeMax"] = _ensure_tz(
                end if "T" in end else end + "T23:59:59Z"
            )
    else:
        now = datetime.now(timezone.utc)
        params["timeMin"] = now.isoformat()
        params["timeMax"] = (now + timedelta(days=7)).isoformat()

    if keyword:
        params["q"] = keyword

    try:
        events = service.events().list(**params).execute().get("items", [])
    except Exception as e:
        return [{"error": f"Calendar query failed: {e}"}]

    if attendees:
        want = {a.lower() for a in attendees}
        events = [
            e for e in events
            if want & {
                a["email"].lower()
                for a in e.get("attendees", [])
                if "email" in a
            }
        ]

    return [_slim_event(e) for e in events]


def _slim_event(e: dict) -> dict:
    """Strip a raw Google Calendar event to only the fields the agent needs."""
    return {
        "id": e.get("id"),
        "summary": e.get("summary", "(no title)"),
        "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
        "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
        "location": e.get("location"),
        "attendees": [
            a.get("email") for a in e.get("attendees", []) if "email" in a
        ] or None,
    }


def _get_calendar_event(event_id):
    """Fetch a single calendar event by its Google Calendar event ID."""
    try:
        service = _get_service()
        return service.events().get(calendarId="primary", eventId=event_id).execute()
    except Exception as e:
        return {"error": f"Failed to fetch event: {e}"}
