"""
Evaluation harness for Vishal's Twin agent.

Run this file directly to execute all tests:

    python -m tests.test_evaluation
or:
    python tests/test_evaluation.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import os
import sys

from langchain_core.messages import AIMessage, ToolMessage

# Make sure project root is on sys.path when running as a script
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from agent import GRAPH


@dataclass
class TestCase:
    name: str
    query: str
    expected_topics: List[str]
    minimum_confidence: float
    category: str


TEST_CASES: List[TestCase] = [
    # ============================================================
    # FACTUAL - Professional Background
    # ============================================================
    TestCase(
        name="Education Background",
        query="Where did Vishal go to school and what did he study?",
        expected_topics=[
            "University of Illinois",
            "Computer Engineering",
            "Master of Computer Science",
        ],
        minimum_confidence=0.6,
        category="factual",
    ),
    TestCase(
        name="Technical Skills - Languages",
        query="What programming languages does Vishal know?",
        expected_topics=["Python", "JavaScript", "C#", "SQL"],
        minimum_confidence=0.6,
        category="factual",
    ),
    TestCase(
        name="Experience - Aramco RAG System",
        query="What experience does Vishal have building RAG or LLM systems?",
        expected_topics=["Aramco", "RAG", "LangChain"],
        minimum_confidence=0.6,
        category="factual",
    ),
    TestCase(
        name="Projects - BetGlobal",
        query="Tell me about the BetGlobal project Vishal built.",
        expected_topics=["BetGlobal", "Flask", "React", "PostgreSQL"],
        minimum_confidence=0.6,
        category="factual",
    ),
    TestCase(
        name="Career Goals",
        query="What are Vishal's career goals?",
        expected_topics=["ownership", "impact", "startup", "AI"],
        minimum_confidence=0.6,
        category="factual",
    ),
    # ============================================================
    # CALENDAR - Google Calendar
    # ============================================================
    TestCase(
        name="Calendar - This Week Schedule",
        query="What do I have on my calendar this week?",
        expected_topics=["Geospatial AI", "class", "CS 598"],
        minimum_confidence=0.5,
        category="calendar",
    ),
    TestCase(
        name="Calendar - Next 7 Days Availability",
        query="What do I have Wed Mar 4th?",
        expected_topics=["CS 598", "Viven"],
        minimum_confidence=0.5,
        category="calendar",
    ),

    # ============================================================
    # EMAIL - Outlook
    # ============================================================
    TestCase(
        name="Email - Recent Messages Summary",
        query="Can you recover my most recent email from Discord?",
        expected_topics=["Discord", "sent", "messages"],
        minimum_confidence=0.5,
        category="email",
    ),
    TestCase(
        name="Email - Search by Keyword",
        query="Do I have any emails about Aramco?",
        expected_topics=["email", "Aramco"],
        minimum_confidence=0.5,
        category="email",
    ),
    # ============================================================
    # HALLUCINATION TESTS
    # ============================================================
    TestCase(
        name="Hallucination - Unknown Favorite Color",
        query="What is Vishal's favorite color?",
        expected_topics=["don't", "not sure", "info", "does not"],
        minimum_confidence=0.0,
        category="hallucination_test",
    ),
    TestCase(
        name="Hallucination - Home Address",
        query="What is Vishal's home address?",
        expected_topics=["privacy", "can't", "share"],
        minimum_confidence=0.0,
        category="hallucination_test",
    ),
    # ============================================================
    # SYNTHESIS - Multi-Source
    # ============================================================
    TestCase(
        name="Synthesis - AI/ML Experience",
        query="Based on Vishal's background, why is he a good fit for an AI/ML engineering role?",
        expected_topics=["AWS", "ML", "RAG", "Python"],
        minimum_confidence=0.6,
        category="synthesis",
    ),
    TestCase(
        name="Synthesis - Systems + Product",
        query="How do Vishal's backend, cloud, and product experiences fit together?",
        expected_topics=["AWS", "microservices", "full-stack", "impact"],
        minimum_confidence=0.6,
        category="synthesis",
    ),
]


def _parse_messages(messages: List[Any]) -> tuple[List[Dict[str, Any]], str]:
    """Walk messages from GRAPH and extract tool steps and final reply."""
    steps: List[Dict[str, Any]] = []
    reply: str = ""
    pending: Dict[str, int] = {}

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                idx = len(steps)
                steps.append(
                    {
                        "type": "tool_call",
                        "name": tc["name"],
                        "args": tc["args"],
                        "result": None,
                        "tool_call_id": tc["id"],
                    }
                )
                pending[tc["id"]] = idx
        elif isinstance(msg, ToolMessage):
            idx = pending.get(msg.tool_call_id)
            if idx is not None:
                steps[idx]["result"] = msg.content
        elif isinstance(msg, AIMessage) and not msg.tool_calls:
            reply = msg.content

    return steps, reply


def process_query(query: str, thread_id: str = "evaluation") -> Dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}

    # Only look at messages generated in this turn
    state = GRAPH.get_state(config)
    n_prev = len(state.values.get("messages", [])) if state.values else 0

    result = GRAPH.invoke({"messages": [("user", query)]}, config=config)
    new_messages = result["messages"][n_prev:]

    steps, reply = _parse_messages(new_messages)
    sources = [s["result"] for s in steps if s.get("result") is not None]

    confidence = 1.0 if sources else 0.7

    return {
        "answer": reply or "",
        "confidence": float(confidence),
        "sources": sources,
    }


def run_evaluation() -> Dict[str, Any]:
    print("Running Vishal's Twin Evaluation Tests\n")
    print("=" * 70)

    passed_tests = 0
    failed_tests = 0
    results: List[Dict[str, Any]] = []
    category_stats: Dict[str, Dict[str, int]] = {}

    for test_case in TEST_CASES:
        print(f"\nTest: {test_case.name} [{test_case.category}]")
        print(f'Query: "{test_case.query}"')

        try:
            response = process_query(test_case.query)
            answered_lower = response["answer"].lower()

            topics_found = [
                topic
                for topic in test_case.expected_topics
                if topic.lower() in answered_lower
            ]

            meets_confidence = response["confidence"] >= test_case.minimum_confidence

            topic_coverage = (
                len(topics_found) / len(test_case.expected_topics)
                if test_case.expected_topics
                else 1.0
            )
            topic_threshold = 1.0 if len(test_case.expected_topics) <= 2 else 0.5

            # Passing criteria:
            # - For normal tests: enough topic coverage + confidence
            # - For hallucination tests: answer clearly expresses uncertainty
            if test_case.category == "hallucination_test":
                # Treat expected_topics as "uncertainty signals" (only need ONE of them),
                # and also allow a small default list of generic uncertainty phrases.
                uncertainty_phrases = [
                    "don't know",
                    "do not know",
                    "not sure",
                    "no idea",
                    "no information",
                    "can't say",
                    "cannot say",
                    "don't have that",
                    "can't share",
                    "cannot share",
                    "for privacy",
                    "for safety reasons",
                ]
                expected_signals = [t.lower() for t in test_case.expected_topics]
                is_uncertain = any(
                    sig in answered_lower for sig in expected_signals + uncertainty_phrases
                )
                passed = is_uncertain and meets_confidence
            else:
                passed = topic_coverage >= topic_threshold and meets_confidence

            if passed:
                passed_tests += 1
                print("PASSED")
            else:
                failed_tests += 1
                print("FAILED")
                if topic_coverage < topic_threshold:
                    print(
                        f"   Topic coverage: {topic_coverage * 100:.0f}% "
                        f"(need {topic_threshold * 100:.0f}%)"
                    )
                    print(
                        f"   Expected: {', '.join(test_case.expected_topics) or 'none'}"
                    )
                    print(f"   Found:    {', '.join(topics_found) or 'none'}")
                if not meets_confidence:
                    print(
                        f"   Confidence: {response['confidence'] * 100:.1f}% "
                        f"(need {test_case.minimum_confidence * 100:.1f}%)"
                    )

            preview = response["answer"][:200].replace("\n", " ")
            print(f"Response: {preview}...")
            print(
                "Confidence: "
                f"{response['confidence'] * 100:.1f}% | "
                f"Topics: {len(topics_found)}/{len(test_case.expected_topics)} | "
                f"Sources: {len(response['sources'])}"
            )

            if test_case.category not in category_stats:
                category_stats[test_case.category] = {"passed": 0, "total": 0}
            category_stats[test_case.category]["total"] += 1
            if passed:
                category_stats[test_case.category]["passed"] += 1

            results.append(
                {
                    "testCase": test_case.name,
                    "category": test_case.category,
                    "passed": passed,
                    "response": response["answer"],
                    "confidence": response["confidence"],
                    "sources": len(response["sources"]),
                    "topicCoverage": topic_coverage,
                    "topicsFound": len(topics_found),
                    "topicsExpected": len(test_case.expected_topics),
                }
            )

        except Exception as error:  # noqa: BLE001
            print("ERROR:", str(error))
            failed_tests += 1
            if test_case.category not in category_stats:
                category_stats[test_case.category] = {"passed": 0, "total": 0}
            category_stats[test_case.category]["total"] += 1
            results.append(
                {
                    "testCase": test_case.name,
                    "category": test_case.category,
                    "passed": False,
                    "error": str(error),
                }
            )

    # Summary
    print("\n" + "=" * 70)
    print("\nEvaluation Summary")
    print("=" * 70)
    print(
        f"\nOverall: {passed_tests}/{len(TEST_CASES)} passed "
        f"({passed_tests / len(TEST_CASES) * 100:.1f}%)"
    )

    print("\nBy Category:")
    for cat, stats in category_stats.items():
        rate = (stats["passed"] / stats["total"] * 100) if stats["total"] else 0.0
        filled = round(stats["passed"] / stats["total"] * 10) if stats["total"] else 0
        bar = "█" * filled + "░" * (10 - filled)
        print(f"  {cat.ljust(20)} {bar} {stats['passed']}/{stats['total']} ({rate:.0f}%)")

    # Aggregate metrics
    valid_results = [r for r in results if "confidence" in r]
    if valid_results:
        avg_conf = sum(r["confidence"] for r in valid_results) / len(valid_results)
    else:
        avg_conf = 0.0

    cov_results = [r for r in results if "topicCoverage" in r]
    if cov_results:
        avg_cov = sum(r["topicCoverage"] for r in cov_results) / len(cov_results)
    else:
        avg_cov = 0.0

    src_results = [r for r in results if "sources" in r]
    if src_results:
        avg_src = sum(r["sources"] for r in src_results) / len(src_results)
    else:
        avg_src = 0.0

    # Hallucination rate: fraction of hallucination tests that failed.
    hall_tests = [r for r in results if r.get("category") == "hallucination_test" and "passed" in r]
    hall_rate = (
        len([r for r in hall_tests if not r["passed"]]) / len(hall_tests)
        if hall_tests
        else 0.0
    )

    print("\nQuality:")
    print(f"  Avg Confidence:     {avg_conf * 100:.1f}%")
    print(f"  Avg Topic Coverage: {avg_cov * 100:.1f}%")
    print(f"  Avg Sources:        {avg_src:.1f}")
    print(f"  Hallucination Rate: {hall_rate * 100:.1f}%")
    print("\n" + "=" * 70)

    summary = {
        "total": len(TEST_CASES),
        "passed": passed_tests,
        "failed": failed_tests,
        "successRate": passed_tests / len(TEST_CASES) if TEST_CASES else 0.0,
        "categoryStats": category_stats,
        "metrics": {
            "avgConf": avg_conf,
            "avgCov": avg_cov,
            "avgSrc": avg_src,
            "hallRate": hall_rate,
        },
    }

    return {"results": results, "summary": summary}


if __name__ == "__main__":
    out = run_evaluation()
    print(
        f"\nDone! Success rate: {out['summary']['successRate'] * 100:.1f}% "
        f"({out['summary']['passed']}/{out['summary']['total']} passed)"
    )

