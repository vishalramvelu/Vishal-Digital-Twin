"""tools/outlook.py — MSFT Graph API for Outlook mail."""

import atexit
import os
from pathlib import Path

from dotenv import load_dotenv
import msal
import requests

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
CLIENT_ID = os.environ["OUTLOOK_CLIENT_ID"]
TENANT_ID = os.environ["OUTLOOK_TENANT_ID"]
SCOPES = ["Mail.Read", "Mail.ReadWrite", "Mail.Send"]
CACHE_PATH = Path(__file__).resolve().parent.parent / ".msal_token_cache.json"

_cache = msal.SerializableTokenCache()
if CACHE_PATH.exists():
    _cache.deserialize(CACHE_PATH.read_text())

_msal_app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    token_cache=_cache,
)


def _save_cache():
    if _cache.has_state_changed:
        CACHE_PATH.write_text(_cache.serialize())


atexit.register(_save_cache)


def _get_access_token():
    accounts = _msal_app.get_accounts()
    if accounts:
        result = _msal_app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]

    flow = _msal_app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow failed: {flow.get('error_description', flow)}")

    print(flow["message"])
    result = _msal_app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _save_cache()
        return result["access_token"]
    raise RuntimeError(f"Token acquisition failed: {result.get('error_description', result)}")


def _graph_get(endpoint, params=None):
    resp = requests.get(
        f"{GRAPH_BASE}{endpoint}",
        headers={"Authorization": f"Bearer {_get_access_token()}"},
        params=params,
    )
    resp.raise_for_status()
    return resp.json()


def _graph_post(endpoint, json=None):
    resp = requests.post(
        f"{GRAPH_BASE}{endpoint}",
        headers={
            "Authorization": f"Bearer {_get_access_token()}",
            "Content-Type": "application/json",
        },
        json=json,
    )
    resp.raise_for_status()
    return resp.json()


def _graph_patch(endpoint, json=None):
    resp = requests.patch(
        f"{GRAPH_BASE}{endpoint}",
        headers={
            "Authorization": f"Bearer {_get_access_token()}",
            "Content-Type": "application/json",
        },
        json=json,
    )
    resp.raise_for_status()
    return resp.json()


# ── Public helpers called by agent tools ──────────────────────────────


def _search_email(query, date_range=None):
    """Search Outlook mail via Microsoft Graph.

    Uses $search for free-text matching across subjects, bodies, senders,
    and recipients. Works with names, emails, keywords, or any combination.

    Returns a list of message dicts (max 25, newest first).
    """
    endpoint = "/me/messages"
    params = {
        "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,conversationId",
        "$top": 25,
    }

    params["$search"] = f'"{query}"'

    filters = []
    if date_range:
        start, end = date_range
        if start:
            filters.append(f"receivedDateTime ge {start}")
        if end:
            filters.append(f"receivedDateTime le {end}")
    if filters:
        params["$filter"] = " and ".join(filters)

    try:
        return _graph_get(endpoint, params).get("value", [])
    except requests.HTTPError as e:
        return [{"error": f"Search failed: {e.response.status_code} — {e.response.text[:200]}"}]


def _get_email(message_id):
    """Fetch a single email by its Graph message ID."""
    try:
        return _graph_get(
            f"/me/messages/{message_id}",
            params={
                "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,conversationId"
            },
        )
    except requests.HTTPError as e:
        return {"error": f"Failed to fetch email: {e.response.status_code} — {e.response.text[:200]}"}


def _get_email_thread(message_id):
    """Fetch all messages in the same conversation as the given message."""
    msg = _get_email(message_id)
    if "error" in msg:
        return [msg]
    cid = msg["conversationId"]
    try:
        return _graph_get(
            "/me/messages",
            params={
                "$filter": f"conversationId eq '{cid}'",
                "$orderby": "receivedDateTime asc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments",
                "$top": 50,
            },
        ).get("value", [])
    except requests.HTTPError as e:
        return [{"error": f"Failed to fetch thread: {e.response.status_code} — {e.response.text[:200]}"}]


def _create_draft_reply(message_id, body):
    """Create a draft reply to the given message with the supplied body text."""
    try:
        draft = _graph_post(f"/me/messages/{message_id}/createReply")
        draft = _graph_patch(
            f"/me/messages/{draft['id']}",
            json={"body": {"contentType": "text", "content": body}},
        )
        return draft
    except requests.HTTPError as e:
        return {"error": f"Failed to create draft: {e.response.status_code} — {e.response.text[:200]}"}
