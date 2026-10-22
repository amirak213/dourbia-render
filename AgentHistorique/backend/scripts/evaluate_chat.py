"""Evaluate end-to-end chat quality against data/eval/chat_questions.json.

Run from backend/:
    python scripts/evaluate_chat.py
    python scripts/evaluate_chat.py --provider mock
    python scripts/evaluate_chat.py --verbose
    python scripts/evaluate_chat.py --output ../data/processed/chat_eval_results.json
    python scripts/evaluate_chat.py --case-id C01
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.local_orchestrator import LocalOrchestrator
from app.config import get_settings
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.rag.prompts import INSUFFICIENT_CONTEXT_ANSWER
from app.schemas.chat import ChatRequest, ChatResponse

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "data" / "eval" / "chat_questions.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "data" / "processed" / "chat_eval_results.json"

REFUSAL_PHRASES = (
    "informations suffisantes",
    "ne peux pas la confirmer",
    "ne peux pas confirmer",
    "pas présente dans les sources",
    "pas presente dans les sources",
    "je ne dispose pas",
)


@dataclass
class TurnResult:
    turn_index: int
    message: str
    answer: str
    sources: list[dict[str, Any]]
    memory_context: dict[str, Any]
    suggested_actions: list[str]
    elapsed_ms: float
    checks: dict[str, Any] = field(default_factory=dict)
    automated_pass: bool = True
    automated_failures: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case_id: str
    category: str
    session_id: str
    language: str
    turn_results: list[TurnResult]
    automated_pass: bool
    automated_failures: list[str]


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def title_matches(actual: str | None, expected: str) -> bool:
    actual_norm = normalize_text(actual)
    expected_norm = normalize_text(expected)
    if not actual_norm or not expected_norm:
        return False
    return (
        actual_norm == expected_norm
        or expected_norm in actual_norm
        or actual_norm in expected_norm
    )


def any_source_title_matches(sources: list[dict[str, Any]], expected_titles: list[str]) -> bool:
    for source in sources:
        title = source.get("title")
        if any(title_matches(title, expected) for expected in expected_titles):
            return True
    return False


def is_refusal_answer(answer: str) -> bool:
    normalized = normalize_text(answer)
    insufficient = normalize_text(INSUFFICIENT_CONTEXT_ANSWER)
    if insufficient in normalized:
        return True
    return any(phrase in normalized for phrase in REFUSAL_PHRASES)


def run_automated_checks(
    response: ChatResponse,
    checks: dict[str, Any],
    *,
    provider: str = "groq",
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    sources = [source.model_dump() for source in response.sources]
    memory = response.memory_context.model_dump()
    answer = response.answer

    expect_refusal = checks.get("expect_refusal", False)
    if expect_refusal:
        if provider == "mock":
            pass  # Mock LLM cannot produce real refusals; check with live provider.
        elif not is_refusal_answer(answer):
            failures.append("expected_refusal")
    else:
        if checks.get("expect_sources", False) and not sources:
            failures.append("missing_sources")

        expected_titles = checks.get("source_titles_any") or []
        if expected_titles and not any_source_title_matches(sources, expected_titles):
            failures.append(f"source_title_mismatch:{expected_titles}")

        expected_source_type = checks.get("expect_source_type")
        if expected_source_type and not any(
            source.get("source_type") == expected_source_type for source in sources
        ):
            failures.append(f"source_type_mismatch:{expected_source_type}")

        interests_any = checks.get("memory_interests_any")
        if interests_any:
            actual_interests = {normalize_text(item) for item in memory.get("interests") or []}
            expected = {normalize_text(item) for item in interests_any}
            if not actual_interests.intersection(expected):
                failures.append(f"memory_interests_mismatch:{interests_any}")

        memory_time = checks.get("memory_time_minutes")
        if memory_time is not None and memory.get("available_time_minutes") != memory_time:
            failures.append(
                f"memory_time_mismatch:expected={memory_time},actual={memory.get('available_time_minutes')}"
            )

        mobility = checks.get("memory_mobility_mode")
        if mobility and memory.get("mobility_mode") != mobility:
            failures.append(
                f"memory_mobility_mismatch:expected={mobility},actual={memory.get('mobility_mode')}"
            )

        monuments_any = checks.get("memory_monuments_any")
        if monuments_any:
            actual = [normalize_text(item) for item in memory.get("last_mentioned_monuments") or []]
            expected = [normalize_text(item) for item in monuments_any]
            if not any(
                any(title_matches(actual_title, expected_title) for actual_title in actual)
                for expected_title in expected
            ):
                failures.append(f"memory_monuments_mismatch:{monuments_any}")

    return len(failures) == 0, failures


def load_dataset(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("cases", [])


def evaluate_case(
    orchestrator: LocalOrchestrator,
    case: dict[str, Any],
    *,
    provider: str,
) -> CaseResult:
    case_id = case["id"]
    category = case["category"]
    session_id = case["session_id"]
    language = case.get("language", "fr")
    turns = case["turns"]

    turn_results: list[TurnResult] = []
    case_failures: list[str] = []

    for index, turn in enumerate(turns):
        message = turn["message"]
        checks = turn.get("checks", {})
        started = time.perf_counter()

        request = ChatRequest(session_id=session_id, message=message, language=language)
        response = orchestrator.handle_chat(request)
        elapsed_ms = (time.perf_counter() - started) * 1000

        automated_pass, failures = run_automated_checks(response, checks, provider=provider)
        if not automated_pass:
            case_failures.extend([f"turn{index + 1}:{failure}" for failure in failures])

        turn_results.append(
            TurnResult(
                turn_index=index + 1,
                message=message,
                answer=response.answer,
                sources=[source.model_dump() for source in response.sources],
                memory_context=response.memory_context.model_dump(),
                suggested_actions=response.suggested_actions,
                elapsed_ms=round(elapsed_ms, 1),
                checks=checks,
                automated_pass=automated_pass,
                automated_failures=failures,
            )
        )

    return CaseResult(
        case_id=case_id,
        category=category,
        session_id=session_id,
        language=language,
        turn_results=turn_results,
        automated_pass=len(case_failures) == 0,
        automated_failures=case_failures,
    )


def print_summary(results: list[CaseResult]) -> None:
    total = len(results)
    if total == 0:
        return

    passed = sum(1 for result in results if result.automated_pass)
    latencies = [
        turn.elapsed_ms
        for result in results
        for turn in result.turn_results
    ]
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0

    print("\nChat evaluation summary")
    print(f"  Cases evaluated: {total}")
    print(f"  Automated pass:  {passed}/{total} ({100 * passed / total:.1f}%)")
    print(f"  Mean latency:    {mean_latency:.0f} ms/turn")

    by_category: dict[str, list[CaseResult]] = {}
    for result in results:
        by_category.setdefault(result.category, []).append(result)

    print("\nBy category:")
    for category, category_results in sorted(by_category.items()):
        category_passed = sum(1 for item in category_results if item.automated_pass)
        print(
            f"  {category}: {category_passed}/{len(category_results)} "
            f"({100 * category_passed / len(category_results):.1f}%)"
        )


def print_results_table(results: list[CaseResult], verbose: bool) -> None:
    print("\nDetailed results")
    print(f"{'ID':<6} {'Category':<20} {'Pass':<5} {'Turns':<5} {'Latency(ms)'}")
    print("-" * 70)
    for result in results:
        total_latency = sum(turn.elapsed_ms for turn in result.turn_results)
        print(
            f"{result.case_id:<6} "
            f"{result.category[:20]:<20} "
            f"{('PASS' if result.automated_pass else 'FAIL'):<5} "
            f"{len(result.turn_results):<5} "
            f"{total_latency:.0f}"
        )
        if verbose or not result.automated_pass:
            for turn in result.turn_results:
                status = "PASS" if turn.automated_pass else "FAIL"
                print(f"  T{turn.turn_index} [{status}] {turn.message[:60]}")
                if not turn.automated_pass:
                    print(f"       Failures: {', '.join(turn.automated_failures)}")
                if verbose:
                    print(f"       Answer: {turn.answer[:120]}...")
                    if turn.sources:
                        titles = [source.get("title") for source in turn.sources[:3]]
                        print(f"       Sources: {titles}")


def save_results(
    path: Path,
    results: list[CaseResult],
    *,
    provider: str,
    model: str,
) -> None:
    total = len(results)
    passed = sum(1 for result in results if result.automated_pass)
    payload = {
        "provider": provider,
        "model": model,
        "summary": {
            "total_cases": total,
            "automated_pass": passed,
            "automated_pass_rate": round(passed / total, 4) if total else 0.0,
        },
        "results": [
            {
                **{key: value for key, value in asdict(result).items() if key != "turn_results"},
                "turn_results": [asdict(turn) for turn in result.turn_results],
            }
            for result in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate end-to-end chat quality.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to chat evaluation dataset JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to write JSON results.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Override LLM_PROVIDER (e.g. mock, groq).",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="Run a single case id (e.g. C01, M03).",
    )
    parser.add_argument("--verbose", action="store_true", help="Print answers and sources.")
    return parser.parse_args()


def build_settings(provider: str | None) -> Settings:
    if provider:
        import os

        os.environ["LLM_PROVIDER"] = provider.strip().lower()
        get_settings.cache_clear()
    return get_settings()


def main() -> None:
    configure_logging()
    args = parse_args()

    if not args.dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {args.dataset}")

    cases = load_dataset(args.dataset)
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]
        if not cases:
            raise ValueError(f"Case id not found: {args.case_id}")

    settings = build_settings(args.provider)
    print(f"LLM provider: {settings.llm_provider} | model: {settings.llm_model_name}")

    session = SessionLocal()
    results: list[CaseResult] = []
    try:
        orchestrator = LocalOrchestrator(session)
        for case in cases:
            print(f"Running {case['id']} ({case['category']})...")
            results.append(
                evaluate_case(orchestrator, case, provider=settings.llm_provider)
            )
    finally:
        session.close()

    print_results_table(results, args.verbose)
    print_summary(results)

    failures = [result for result in results if not result.automated_pass]
    if failures:
        print("\nFailed cases:")
        for result in failures:
            print(f"  {result.case_id}: {', '.join(result.automated_failures)}")

    save_results(
        args.output,
        results,
        provider=settings.llm_provider,
        model=settings.llm_model_name,
    )
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
