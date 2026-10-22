"""Evaluate semantic retrieval against docs/retrieval_evaluation.md.

Run from backend/:
    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --verbose
    python scripts/evaluate_retrieval.py --include-filters
    python scripts/evaluate_retrieval.py --output ../data/processed/retrieval_eval_results.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.rag.retriever import RetrievalFilters, SemanticRetriever

MIN_USEFUL_SCORE = 0.65
DEFAULT_TOP_K = 5


@dataclass
class EvalCase:
    question_id: str
    category: str
    question: str
    expected_titles: list[str]
    expected_source_type: str
    expected_destination: str
    filters: RetrievalFilters | None = None
    top1_validator: Callable[[list[dict[str, Any]]], bool] | None = None
    top3_validator: Callable[[list[dict[str, Any]]], bool] | None = None
    notes: str = ""


@dataclass
class EvalResult:
    question_id: str
    category: str
    question: str
    expected_titles: list[str]
    top1_pass: bool
    top3_pass: bool
    source_type_pass: bool
    destination_pass: bool
    score_pass: bool
    actual_top1_title: str | None
    actual_top1_score: float | None
    actual_top3_titles: list[str]
    notes: str = ""


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


def any_title_matches(results: list[dict[str, Any]], expected_titles: list[str]) -> bool:
    for result in results:
        title = result.get("title")
        if any(title_matches(title, expected) for expected in expected_titles):
            return True
    return False


def first_title_matches(results: list[dict[str, Any]], expected_titles: list[str]) -> bool:
    if not results:
        return False
    title = results[0].get("title")
    return any(title_matches(title, expected) for expected in expected_titles)


def has_reduced_accessibility(results: list[dict[str, Any]]) -> bool:
    for result in results:
        accessibility = normalize_text(str(result.get("metadata", {}).get("accessibility", "")))
        if "reduit" in accessibility or "reduced" in accessibility:
            return True
        chunk_text = normalize_text(result.get("chunk_text"))
        if "accessibilite" in chunk_text and "reduit" in chunk_text:
            return True
    return False


def has_short_visit(results: list[dict[str, Any]], max_minutes: float = 15.0) -> bool:
    short_title_hints = [
        "theatre",
        "maison de la basilique",
        "maison de la rotonde",
        "maison du cryptoportique",
        "monastere de bigua",
    ]
    for result in results:
        duration = result.get("metadata", {}).get("visit_duration_minutes")
        if duration is not None and float(duration) <= max_minutes:
            return True
        title = normalize_text(result.get("title"))
        if any(hint in title for hint in short_title_hints):
            return True
    return False


def has_long_visit_target(results: list[dict[str, Any]]) -> bool:
    targets = [
        "colline de byrsa",
        "parc des thermes d'antonin",
    ]
    for result in results:
        title = normalize_text(result.get("title"))
        if any(target in title for target in targets):
            return True
    return False


def build_eval_cases() -> list[EvalCase]:
    punic_alternates = ["Tophet", "Quartier Magon", "Ports puniques", "Colline de Byrsa"]
    accessibility_alternates = [
        "Maison des Lions",
        "Monastere de Bigua",
        "Four punique",
        "Necropole punique",
        "Kobbet el Houwa",
        "Tombe de la Necropole punique",
    ]
    short_visit_alternates = ["Theatre", "Maison de la Basilique", "Maison de la Rotonde"]
    long_visit_alternates = ["Colline de Byrsa", "Parc des thermes d'Antonin"]

    return [
        EvalCase("1", "Roman monuments", "Quels sont les thermes romains à Carthage ?", ["Thermes d'Antonin"], "monument", "Carthage"),
        EvalCase("2", "Roman monuments", "Où se trouve le théâtre romain de Carthage ?", ["Theatre"], "monument", "Carthage"),
        EvalCase("3", "Roman monuments", "Je veux voir un amphithéâtre romain.", ["Amphitheatre De Carthage"], "monument", "Carthage"),
        EvalCase("4", "Roman monuments", "Quels monuments romains peut-on visiter dans le parc des villas ?", ["Parc des villas romaines"], "monument", "Carthage"),
        EvalCase("5", "Roman monuments", "Existe-t-il un odéon romain à Carthage ?", ["Odeon"], "monument", "Carthage"),
        EvalCase("6", "Punic monuments", "Qu'est-ce que le Tophet de Carthage ?", ["Tophet"], "monument", "Carthage"),
        EvalCase(
            "7",
            "Punic monuments",
            "Quels sites puniques peut-on visiter à Carthage ?",
            punic_alternates,
            "monument",
            "Carthage",
            notes="Pass if any major punic monument is in top 3.",
        ),
        EvalCase("8", "Punic monuments", "Où se trouve la colline de Byrsa ?", ["Colline de Byrsa"], "monument", "Carthage"),
        EvalCase("9", "Punic monuments", "Parle-moi des ports puniques.", ["Ports puniques"], "monument", "Carthage"),
        EvalCase("10", "Punic monuments", "Qu'est-ce que le quartier Magon ?", ["Quartier Magon"], "monument", "Carthage"),
        EvalCase("11", "Byzantine monuments", "Quelles basiliques byzantines visiter à Carthage ?", ["Basiliques byzantines"], "monument", "Carthage"),
        EvalCase("12", "Byzantine monuments", "Où se trouve la basilique Saint Cyprien ?", ["Basilique Saint Cyprien"], "monument", "Carthage"),
        EvalCase("13", "Byzantine monuments", "Parle-moi de la basilique Bir Messaouda.", ["Basilique Bir Messaouda"], "monument", "Carthage"),
        EvalCase(
            "14",
            "Byzantine monuments",
            "Y a-t-il un musée paléochrétien à Carthage ?",
            ["Parc du Musee Paleochretien Basilique de Cartagena"],
            "monument",
            "Carthage",
        ),
        EvalCase("15", "Circuits", "Propose un circuit romain à Carthage.", ["Circuit Romain"], "circuit", "Carthage"),
        EvalCase("16", "Circuits", "Je cherche un circuit sur l'époque punique.", ["Circuit Punique"], "circuit", "Carthage"),
        EvalCase("17", "Circuits", "Quel circuit byzantin existe à Carthage ?", ["Circuit Byzantin"], "circuit", "Carthage"),
        EvalCase("18", "Circuits", "J'ai peu de temps, quel circuit demi-journée faire ?", ["Circuit Demi-Journée"], "circuit", "Carthage"),
        EvalCase(
            "19",
            "Circuits",
            "Existe-t-il un circuit à La Marsa ?",
            ["Circuit La Marsa"],
            "circuit",
            "La Marsa",
            notes="Destination metadata may still say Carthage in chunks.",
        ),
        EvalCase(
            "20",
            "Accessibility",
            "Quels monuments ont une accessibilité réduite ?",
            accessibility_alternates,
            "monument",
            "Carthage",
            top3_validator=lambda results: has_reduced_accessibility(results[:3]),
            notes="Pass if reduced accessibility appears in top 3.",
        ),
        EvalCase("21", "Accessibility", "Le théâtre est-il accessible aux visiteurs ?", ["Theatre"], "monument", "Carthage"),
        EvalCase(
            "22",
            "Accessibility",
            "Quels sites puniques sont difficiles d'accès ?",
            ["Four punique", "Necropole punique"],
            "monument",
            "Carthage",
            top3_validator=lambda results: any_title_matches(results[:3], ["Four punique", "Necropole punique"])
            or has_reduced_accessibility(results[:3]),
        ),
        EvalCase("23", "Visit duration", "Combien de temps faut-il pour visiter les Thermes d'Antonin ?", ["Thermes d'Antonin"], "monument", "Carthage"),
        EvalCase(
            "24",
            "Visit duration",
            "Quels monuments se visitent en moins de 15 minutes ?",
            short_visit_alternates,
            "monument",
            "Carthage",
            top3_validator=lambda results: has_short_visit(results[:3]),
        ),
        EvalCase(
            "25",
            "Visit duration",
            "Quel est le monument le plus long à visiter à Carthage ?",
            long_visit_alternates,
            "monument",
            "Carthage",
            top3_validator=lambda results: has_long_visit_target(results[:3]),
        ),
        EvalCase("26", "Historical explanations", "Explique l'histoire du théâtre romain de Carthage.", ["Theatre"], "monument", "Carthage"),
        EvalCase("27", "Historical explanations", "Quelle est l'importance historique du Tophet ?", ["Tophet"], "monument", "Carthage"),
        EvalCase("28", "Historical explanations", "Raconte-moi l'histoire de la colline de Byrsa.", ["Colline de Byrsa"], "monument", "Carthage"),
        EvalCase("29", "Historical explanations", "Que sait-on des ports puniques de Carthage ?", ["Ports puniques"], "monument", "Carthage"),
        EvalCase(
            "30",
            "Historical explanations",
            "Décris le parc des thermes d'Antonin et son contexte historique.",
            ["Parc des thermes d'Antonin"],
            "monument",
            "Carthage",
        ),
    ]


def build_filter_cases() -> list[EvalCase]:
    return [
        EvalCase(
            "F1",
            "Filter test",
            "monuments romains",
            [],
            "monument",
            "Carthage",
            filters=RetrievalFilters(source_type="monument", period="romaine", language="fr"),
            top3_validator=lambda results: len(results) >= 1
            and all(result.get("source_type") == "monument" for result in results[:3]),
            notes="All top 3 results should be monuments.",
        ),
        EvalCase(
            "F2",
            "Filter test",
            "circuit punique",
            ["Circuit Punique"],
            "circuit",
            "Carthage",
            filters=RetrievalFilters(source_type="circuit", period="punique", language="fr"),
        ),
        EvalCase(
            "F3",
            "Filter test",
            "sites byzantins",
            ["Basiliques byzantines", "Basilique Saint Cyprien", "Circuit Byzantin"],
            "monument",
            "Carthage",
            filters=RetrievalFilters(period="byzantine", language="fr"),
            top3_validator=lambda results: any_title_matches(
                results[:3],
                ["Basiliques byzantines", "Basilique Saint Cyprien", "Basilique Bir Messaouda", "Circuit Byzantin"],
            ),
        ),
        EvalCase(
            "F4",
            "Filter test",
            "information Carthage",
            [],
            "monument",
            "Carthage",
            filters=RetrievalFilters(destination="Carthage", language="fr"),
            top3_validator=lambda results: len(results) >= 1
            and all(
                normalize_text(result.get("metadata", {}).get("destination_name")) == "carthage"
                for result in results[:3]
            ),
        ),
        EvalCase(
            "F5",
            "Filter test",
            "circuit vélo",
            ["Circuit Carthage_cyclable", "Circuit Saint Augustin_cyclable"],
            "circuit",
            "Carthage",
            filters=RetrievalFilters(source_type="circuit", language="fr"),
            top3_validator=lambda results: any(
                "cyclable" in normalize_text(result.get("title")) for result in results[:3]
            ),
        ),
    ]


def evaluate_case(retriever: SemanticRetriever, case: EvalCase, top_k: int) -> EvalResult:
    results = retriever.retrieve(case.question, top_k=top_k, filters=case.filters)
    top3 = results[:3]

    top1_pass = (
        case.top1_validator(results)
        if case.top1_validator
        else first_title_matches(results, case.expected_titles)
    )
    top3_pass = (
        case.top3_validator(top3)
        if case.top3_validator
        else any_title_matches(top3, case.expected_titles)
    )

    source_type_pass = any(result.get("source_type") == case.expected_source_type for result in top3)
    destination_pass = any(
        normalize_text(result.get("metadata", {}).get("destination_name"))
        == normalize_text(case.expected_destination)
        for result in top3
    ) if case.expected_destination else True

    actual_top1_title = results[0].get("title") if results else None
    actual_top1_score = float(results[0]["score"]) if results else None
    score_pass = actual_top1_score is not None and actual_top1_score >= MIN_USEFUL_SCORE

    return EvalResult(
        question_id=case.question_id,
        category=case.category,
        question=case.question,
        expected_titles=case.expected_titles,
        top1_pass=top1_pass,
        top3_pass=top3_pass,
        source_type_pass=source_type_pass,
        destination_pass=destination_pass,
        score_pass=score_pass,
        actual_top1_title=actual_top1_title,
        actual_top1_score=actual_top1_score,
        actual_top3_titles=[str(result.get("title") or "") for result in top3],
        notes=case.notes,
    )


def print_summary(results: list[EvalResult], label: str) -> None:
    total = len(results)
    if total == 0:
        return

    top1_count = sum(1 for result in results if result.top1_pass)
    top3_count = sum(1 for result in results if result.top3_pass)
    score_count = sum(1 for result in results if result.score_pass)
    top1_scores = [result.actual_top1_score for result in results if result.actual_top1_score is not None]
    mean_top1_score = sum(top1_scores) / len(top1_scores) if top1_scores else 0.0

    print(f"\n{label}")
    print(f"  Questions evaluated: {total}")
    print(f"  Top-1 accuracy: {top1_count}/{total} ({100 * top1_count / total:.1f}%)")
    print(f"  Top-3 recall:   {top3_count}/{total} ({100 * top3_count / total:.1f}%)")
    print(f"  Score >= {MIN_USEFUL_SCORE}: {score_count}/{total} ({100 * score_count / total:.1f}%)")
    print(f"  Mean top-1 score: {mean_top1_score:.3f}")

    baseline_top1 = 0.70
    baseline_top3 = 0.85
    if label.startswith("Main evaluation"):
        if top1_count / total >= baseline_top1 and top3_count / total >= baseline_top3:
            print("  Baseline: PASS (>= 70% top-1 and >= 85% top-3)")
        else:
            print("  Baseline: BELOW TARGET (goal: >= 70% top-1, >= 85% top-3)")


def print_results_table(results: list[EvalResult], verbose: bool) -> None:
    print("\nDetailed results")
    print(f"{'Q#':<4} {'Category':<22} {'Top1':<5} {'Top3':<5} {'Score':<7} {'Top-1 title'}")
    print("-" * 90)
    for result in results:
        score_text = f"{result.actual_top1_score:.3f}" if result.actual_top1_score is not None else "n/a"
        print(
            f"{result.question_id:<4} "
            f"{result.category[:22]:<22} "
            f"{('PASS' if result.top1_pass else 'FAIL'):<5} "
            f"{('PASS' if result.top3_pass else 'FAIL'):<5} "
            f"{score_text:<7} "
            f"{result.actual_top1_title or 'n/a'}"
        )
        if verbose:
            print(f"     Q: {result.question}")
            if result.expected_titles:
                print(f"     Expected: {', '.join(result.expected_titles)}")
            print(f"     Top 3: {', '.join(result.actual_top3_titles) or 'n/a'}")
            if result.notes:
                print(f"     Notes: {result.notes}")


def save_results(path: Path, main_results: list[EvalResult], filter_results: list[EvalResult]) -> None:
    payload = {
        "main_results": [result.__dict__ for result in main_results],
        "filter_results": [result.__dict__ for result in filter_results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality using predefined questions.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of results to retrieve.")
    parser.add_argument("--verbose", action="store_true", help="Print question details and top-3 titles.")
    parser.add_argument("--include-filters", action="store_true", help="Also run filter-specific test cases F1-F5.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write JSON results.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")

    session = SessionLocal()
    try:
        retriever = SemanticRetriever(session)
        main_cases = build_eval_cases()
        main_results = [evaluate_case(retriever, case, args.top_k) for case in main_cases]

        filter_results: list[EvalResult] = []
        if args.include_filters:
            filter_results = [
                evaluate_case(retriever, case, args.top_k) for case in build_filter_cases()
            ]
    finally:
        session.close()

    print_results_table(main_results, args.verbose)
    print_summary(main_results, "Main evaluation (30 questions)")

    if filter_results:
        print_results_table(filter_results, args.verbose)
        print_summary(filter_results, "Filter tests (F1-F5)")

    failures = [result for result in main_results if not result.top3_pass]
    if failures:
        print("\nFailed top-3 cases:")
        for result in failures:
            print(f"  Q{result.question_id}: expected {result.expected_titles} -> got {result.actual_top3_titles}")

    if args.output:
        save_results(args.output, main_results, filter_results)
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
