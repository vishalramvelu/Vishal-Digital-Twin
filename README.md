# Vishal's Twin

An agentic RAG system that acts as my digital twin. Ask it anything about my background, skills, experience, or schedule. It responds as me, grounded in real data.

Built as a take-home for [Viven](https://viven.ai). Deep-dive focus: **Data Integrations** (Outlook + Google Calendar).

## Architecture

```
                          +------------------+
                          |    Visitor UI    |
                          |  (React / Flask) |
                          +--------+---------+
                                   |
                              POST /chat
                                   |
                          +--------v---------+
                          |   LangGraph Agent |
                          |  (gpt-4o-mini)   |
                          +--------+---------+
                                   |
                    The agent decides which tools to call
                    based on the visitor's question.
                                   |
              +--------------------+--------------------+
              |                    |                    |
    +---------v--------+  +-------v--------+  +--------v--------+
    |  query_profile   |  |  Outlook Email |  | Google Calendar |
    |  (RAG Retriever) |  |  (MS Graph)    |  |  (Calendar API) |
    +---------+--------+  +-------+--------+  +--------+--------+
              |                    |                    |
    +---------v--------+   OAuth 2.0 + REST      OAuth 2.0 + REST
    | InMemoryVector   |          |                    |
    | Store (embedded  |   +------v------+      +------v------+
    | profile chunks)  |   | search      |      | list events |
    +------------------+   | get         |      | get event   |
                           | get_thread  |      +-------------+
                           | draft_reply |
                           +-------------+
```

### How the agent thinks

The LLM receives the system prompt (which frames it as Vishal speaking to an external visitor) and a list of 7 tools. For each message, it autonomously decides:

1. **Profile questions** ("tell me about yourself", "what's your AWS experience?") → calls `query_profile` to retrieve relevant chunks from the vector store, then synthesizes a first-person answer.
2. **Scheduling questions** ("are you free next week?") → calls `list_calendar_events` / `get_calendar_event` to check real availability.
3. **Email questions** ("did you get my message?") → calls `search_email` / `get_email` / `get_email_thread` to find relevant correspondence.
4. **Relay requests** ("tell Vishal I said hi") → calls `create_draft_reply` to save a draft for Vishal's review. Never sends.
5. **General conversation** → responds directly without tools when no data lookup is needed.

### RAG pipeline

```
profile.json (25 chunks) + github.json (repo chunks)
        |
   _load_chunks()          Each chunk is a self-contained paragraph
        |                  with metadata (id, category, tags)
        v
  OpenAI Embeddings        text-embedding-3-small
        |
        v
  InMemoryVectorStore      Built once at startup (singleton)
        |
        v
  retriever (k=8)          Top-8 similarity search per query
        |
        v
  query_profile(query)     Returns concatenated chunk text
```

The profile data is structured as 25 natural-language chunks spanning identity, education, 6 work experiences, 2 projects, skills (4 chunks), honors, career goals, interests, work style, communication approach, hobbies, and favorites. GitHub project metadata (READMEs, tech stacks, overviews) is auto-fetched via `scripts/fetch_github.py` and stored in `memory/github.json`. All chunks embed independently and retrieve well on their own.

**Why no grading/rewrite loop?** The corpus is small and high-quality. Top-8 retrieval with `text-embedding-3-small` is enough so adding a relevance grader and query rewriter would add latency and token cost without meaningful accuracy gain at this scale.

### Privacy model

The system prompt enforces:
- Profile data (resume, skills, projects) is shared freely
- Calendar shows free/busy status but redacts meeting titles and attendees
- Email content is summarized, never dumped raw
- Drafts are saved for Vishal's review, never sent
- Unprofessional or privacy-probing requests are declined

## Project structure

```
.
├── app.py                  Flask server (/, /chat, /usage)
├── agent.py                LangGraph agent + 7 tool definitions
├── RAG.py                  Vector store builder + query_profile retriever
├── memory/
│   ├── system.md           System prompt (persona, rules, tool guidance)
│   ├── profile.json        25 RAG-ready chunks with metadata
│   └── github.json         GitHub project metadata (auto-generated)
├── tools/
│   ├── outlook.py          Microsoft Graph API (email CRUD)
│   └── google.py           Google Calendar API (events)
├── scripts/
│   └── fetch_github.py     Scrapes GitHub repos → github.json
├── templates/
│   ├── base.html           HTML shell (React CDN)
│   └── index.html          Chat UI (React + Babel)
├── tests/
│   └── test_evaluation.py  Evaluation harness (5 categories)
└── requirements.txt
```

## Setup

```bash
# 1. Clone and install
git clone <repo-url> && cd vish_twin
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in:
#   OPEN_AI_KEY          — OpenAI API key
#   OUTLOOK_CLIENT_ID    — Azure app registration
#   OUTLOOK_TENANT_ID    — Azure tenant
#   OUTLOOK_CLIENT_SECRET
#   OUTLOOK_USER_EMAIL
#   GOOG_CLIENT_ID       — Google OAuth client
#   GOOG_CLIENT_SECRET
#   GOOG_REFRESH_TOKEN
#   GITHUB_TOKEN         — GitHub PAT (optional, for rate limits)

# 3. Run
python app.py
# Open http://localhost:8001
```

## Tools

| Tool | Source | Purpose |
|---|---|---|
| `query_profile` | RAG.py | Semantic search over Vishal's profile (resume, skills, goals, etc.) |
| `search_email` | tools/outlook.py | Search Outlook inbox by keyword, sender, date range |
| `get_email` | tools/outlook.py | Fetch full email by ID |
| `get_email_thread` | tools/outlook.py | Retrieve full conversation thread |
| `create_draft_reply` | tools/outlook.py | Draft a reply (saved, never sent) |
| `list_calendar_events` | tools/google.py | List upcoming events with filters |
| `get_calendar_event` | tools/google.py | Get full event details |

## Scripts

```bash
# Refresh GitHub project data (rebuilds memory/github.json)
python scripts/fetch_github.py
```

## Evaluation / Testing

The repo includes an evaluation harness in `tests/test_evaluation.py` that runs the agent against a fixed set of test cases and reports pass/fail and per-category metrics.

**Run from project root:**

```bash
python tests/test_evaluation.py
# or
python -m tests.test_evaluation
```

**Test categories:**

| Category | Description |
|----------|-------------|
| **factual** | Profile questions (education, skills, experience, projects, career goals) — answer must hit expected topic coverage and confidence. |
| **calendar** | Google Calendar (e.g. "What do I have this week?", "Am I free in the next 7 days?") — validates calendar tool usage and response shape. |
| **email** | Outlook (e.g. "Summarize my recent emails", "Do I have emails about X?") — validates email search/summary behavior. |
| **hallucination_test** | Questions the profile doesn't answer (favorite color, home address) — passes if the answer expresses uncertainty (e.g. "I don't know", "can't share") without requiring every phrase. |
| **synthesis** | Multi-source reasoning (e.g. "Why am I a good fit for an AI role?") — topic coverage + confidence. |

Results: 13/13 tests passed (100%)

## Design decisions & tradeoffs

- **LangGraph for agent orchestration**: The twin uses LangGraph to orchestrate the LLM and the seven tools (profile RAG, Outlook, Google Calendar). The graph handles the tool-calling loop. The model decides when to call tools, tool results are fed back into the conversation, and the model can call multiple tools in one turn or respond directly when no lookup is needed. Another way would be to simply have a single-pass pipeline where we run RAG to fetch context, then do one LLM call to answer strictly from that context. That approach is cheaper/simpler and great for “profile-only Q&A”, but it is less effective with calendar/email lookups, multi-step actions, or dynamic tool routing. LangGraph keeps the agent logic in one place and makes it easy to add tools and do more advanced requests.
- **InMemoryVectorStore over FAISS/Pinecone**: 25 chunks don't need a database. In-memory is zero-config, fast, and sufficient. Would switch to a persistent store if the corpus grew (e.g., indexing emails, Slack messages, documents).
- **text-embedding-3-small**: Cheapest OpenAI embedding model. Good enough for a curated corpus where chunks are already written as clean natural language.
- **Session-wise conversation memory**: Each chat session maintains multi-turn context via LangGraph's `MemorySaver` checkpointer. The frontend generates a `thread_id` per session (reset on "New Chat"), and the backend slices only new messages per turn to avoid duplicate token counting.
- **gpt-4o-mini over GPT-5**: The take-home asks for mini/nano models. `gpt-4o-mini` is 5-10x faster and cheap while still handling tool routing well. Could swap to `gpt-4o` or `gpt-5` for better quality at higher cost/latency.
- **Slim calendar responses**: Raw Google Calendar API events are ~400 chars each with metadata the LLM doesn't need. `_slim_event()` trims to ~100 chars (id, summary, start, end, location, attendees), cutting context size by ~75% and reducing LLM processing time.


## Future extensions

- **Persistent conversation memory**: Replace in-memory checkpointer with a database-backed one (e.g., `langgraph-checkpoint-postgres`) so conversations survive server restarts
- **Email RAG**: Vectorize email history for semantic search beyond keyword matching
- **Twin sharing**: Scoped access levels (public profile vs. full email/calendar) per visitor and adding a layer of authentication to limit access to the twin
- **Response evaluation**: Expand the eval harness with more cases, regression baselines, and retrieval-precision metrics
- **Additional Data Sources**: Integrate in Slack for conversations, Google Drive for project work, access to sending emails in Outlook/Gmail. Add new sources to expand twin's abiltiies and usefulness
