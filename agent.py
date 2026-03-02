"""
agent.py — langgraph agent graph, tool definitions, and REPL
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from tools.outlook import _search_email, _get_email, _get_email_thread, _create_draft_reply
from tools.google import _list_calendar_events, _get_calendar_event
from RAG import query_profile as _query_profile

load_dotenv()

_SYSTEM_TEMPLATE = (Path(__file__).parent / "memory" / "system.md").read_text()
SYSTEM_PROMPT = _SYSTEM_TEMPLATE.replace(
    "{date}", datetime.now(timezone.utc).strftime("%A, %B %d, %Y (%Y-%m-%d)")
)


# ── Tool definitions ──────────────────────────────────────────────────

@tool
def query_profile(query: str) -> str:
    """Search Vishal's profile for information about his background, skills,
    experience, projects, education, goals, hobbies, favorites, or preferences.
    Use this whenever the visitor asks about who Vishal is, what he's done,
    what he knows, or personal likes (e.g. favorite food, team, artist).

    In:
        query (str): Natural-language question or topic to search for.
    Out:
        str: The most relevant profile passages about Vishal.
    """
    return _query_profile(query)


@tool
def search_email(
    query: str,
    date_range: list[str] | None = None,
) -> list[dict]:
    """Search Vishal's Outlook inbox. Use when the visitor asks about emails,
    messages, or correspondence.

    In:
        query (str): Free-text search across subjects, bodies, senders, and
            recipients. Include names, keywords, or topics to find relevant
            emails. Examples: "gabriela medina", "aramco travel", "meeting friday".
        date_range (list[str] | None): Two-element list [start, end] of
            ISO-8601 datetimes to bound the search window.
    Out:
        list[dict]: Up to 25 message summaries (newest first), each with id,
            subject, from, receivedDateTime, bodyPreview, hasAttachments, and
            conversationId.
    """
    return _search_email(query, date_range)


@tool
def get_email(message_id: str) -> dict:
    """Fetch the full content of one email by its ID. Use this when the visitor
    asks for more details, full content, or "more info" about a specific message
    from a list you just returned — use that message's id from the search_email
    results. Do not use query_profile for "more info on message N".

    In:
        message_id (str): The Outlook Graph message ID (from search_email results).
    Out:
        dict: Full message with id, subject, from, toRecipients, ccRecipients,
            receivedDateTime, body (HTML), hasAttachments, and conversationId.
    """
    return _get_email(message_id)


@tool
def get_email_thread(message_id: str) -> list[dict]:
    """Retrieve every message in the same conversation as the given email.
    Use when the user wants to see the full back-and-forth of a thread.

    In:
        message_id (str): Any message ID belonging to the conversation.
    Out:
        list[dict]: Up to 50 messages in chronological order, each with id,
            subject, from, receivedDateTime, bodyPreview, and hasAttachments.
    """
    return _get_email_thread(message_id)


@tool
def create_draft_reply(message_id: str, body: str) -> dict:
    """Create a draft reply to an email. Use when the user wants to respond to
    a message. The draft is saved but NOT sent — the user must review and send
    it manually.

    In:
        message_id (str): The ID of the message to reply to.
        body (str): The plain-text reply body to include in the draft.
    Out:
        dict: The created draft message object, including its id and body.
    """
    return _create_draft_reply(message_id, body)


@tool
def list_calendar_events(
    date_range: list[str] | None = None,
    attendees: list[str] | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """List upcoming Google Calendar events. Use when the user asks about their
    schedule, meetings, or availability. Combine filters to narrow results.

    In:
        date_range (list[str] | None): Two-element list [start, end] of
            ISO-8601 datetimes. Defaults to the next 7 days if omitted.
        attendees (list[str] | None): Email addresses — only return events
            where at least one of these people is an attendee.
        keyword (str | None): Free-text search across event titles and
            descriptions.
    Out:
        list[dict]: Up to 25 events ordered by start time, each with id,
            summary, start, end, attendees, location, and description.
    """
    return _list_calendar_events(date_range, attendees, keyword)


@tool
def get_calendar_event(event_id: str) -> dict:
    """Fetch full details of a single Google Calendar event. Use after
    list_calendar_events to get the complete event including description,
    conference link, and full attendee list.

    In:
        event_id (str): The Google Calendar event ID.
    Out:
        dict: Complete event object with id, summary, description, start, end,
            attendees, location, hangoutLink, and conferenceData.
    """
    return _get_calendar_event(event_id)


# ── Graph ─────────────────────────────────────────────────────────────

TOOLS = [
    query_profile,
    search_email,
    get_email,
    get_email_thread,
    create_draft_reply,
    list_calendar_events,
    get_calendar_event,
]

MODEL = ChatOpenAI(model="gpt-4o-mini", api_key=os.environ["OPEN_AI_KEY"])

GRAPH = create_agent(MODEL, tools=TOOLS, system_prompt=SYSTEM_PROMPT, checkpointer=MemorySaver())


# ── REPL ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(" Vishal's Twin agent ready. Type 'q' to exit.\n")
    while True:
        user_input = input(" > ").strip()
        if user_input.lower() == 'q':
            break
        if not user_input:
            continue
        config = {"configurable": {"thread_id": "repl"}}
        result = GRAPH.invoke({"messages": [("user", user_input)]}, config=config)
        print(f"\nVishal's Twin: {result['messages'][-1].content}\n")