"""app.py — Flask web server for Vishal's Twin agent"""

import os
import time
import logging

from flask import Flask, render_template, request, jsonify
from langchain_core.messages import AIMessage, ToolMessage

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("vishals-twin")

t0 = time.perf_counter()
log.info("[boot] importing agent + building vector store ...")
from agent import GRAPH
log.info("[boot] ready in %.2fs", time.perf_counter() - t0)

app = Flask(__name__)

# Session-level token usage accumulator
_session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _parse_result(messages):
    """Walk through agent result messages and extract tool call steps, reply, and usage."""
    steps = []
    reply = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # Build a map from tool_call_id -> pending step index so we can pair results
    pending = {}  # tool_call_id -> index in steps

    for msg in messages:
        # Accumulate token usage from every AI message
        if isinstance(msg, AIMessage) and msg.usage_metadata:
            meta = msg.usage_metadata
            usage["prompt_tokens"] += meta.get("input_tokens", 0)
            usage["completion_tokens"] += meta.get("output_tokens", 0)
            usage["total_tokens"] += meta.get("total_tokens", 0)

        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                idx = len(steps)
                steps.append({
                    "type": "tool_call",
                    "name": tc["name"],
                    "args": tc["args"],
                    "result": None,
                })
                pending[tc["id"]] = idx

        elif isinstance(msg, ToolMessage):
            idx = pending.get(msg.tool_call_id)
            if idx is not None:
                steps[idx]["result"] = msg.content

        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            reply = msg.content

    # Update session accumulator
    _session_usage["prompt_tokens"] += usage["prompt_tokens"]
    _session_usage["completion_tokens"] += usage["completion_tokens"]
    _session_usage["total_tokens"] += usage["total_tokens"]

    return steps, reply, usage


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json.get("message", "").strip()
    thread_id = request.json.get("thread_id", "default")
    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    log.info("─" * 50)
    log.info("[query] %s  (thread=%s)", user_msg, thread_id)
    t_start = time.perf_counter()

    config = {"configurable": {"thread_id": thread_id}}

    # Count existing messages so we only parse NEW ones from this turn
    state = GRAPH.get_state(config)
    n_prev = len(state.values.get("messages", [])) if state.values else 0

    result = GRAPH.invoke({"messages": [("user", user_msg)]}, config=config)

    t_agent = time.perf_counter()
    log.info("[agent] total %.2fs", t_agent - t_start)

    new_msgs = result["messages"][n_prev:]

    # Log per-message timing breakdown
    for msg in new_msgs:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            names = ", ".join(tc["name"] for tc in msg.tool_calls)
            log.info("  LLM → tool_calls: %s", names)
        elif isinstance(msg, ToolMessage):
            log.info("  tool result: %s (%d chars)", msg.name, len(str(msg.content)))
        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            log.info("  LLM → final reply (%d chars)", len(msg.content))

    steps, reply, usage = _parse_result(new_msgs)
    log.info("[tokens] prompt=%d completion=%d total=%d",
             usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"])
    return jsonify({"steps": steps, "reply": reply, "usage": usage})


@app.route("/usage")
def usage():
    return jsonify(_session_usage)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    app.run(debug=True, port=port)
