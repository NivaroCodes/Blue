import os
import sys
import json
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from ai_data.models import AnalysisResult, ReasonItem, RiskLevelEnum
from ai_data.heuristics import analyze_with_heuristics
from ai_data.analyzer import synthesize_risk

BENCHMARK_PATH = os.path.join(os.path.dirname(__file__), "flash_lite_benchmark.json")
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
HYBRID_RESULTS_PATH = os.path.join(os.path.dirname(__file__), "hybrid_risk_engine_verification.json")

def verify_hybrid():
    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        benchmark_items = {item["id"]: item for item in json.load(f)}

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        bench_data = json.load(f)

    classes = ["LOW", "MEDIUM", "HIGH"]
    matrix = {actual: {pred: 0 for pred in classes} for actual in classes}

    total_evidence_count = 0
    exact_evidence_count = 0
    lang_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    individual_hybrid_results = []
    medium_as_low = []

    for r in bench_data["individual_results"]:
        item_id = r["id"]
        item = benchmark_items[item_id]
        text = item["text"]
        gt = r["ground_truth_level"]
        lang = item["lang"]

        # Reconstruct cached Gemini response
        gem_reasons = [ReasonItem(code=x["code"], evidence=x["evidence"]) for x in r["reasons"]]
        gem_level = RiskLevelEnum(r["predicted_risk_level"]) if r["predicted_risk_level"] else RiskLevelEnum.LOW
        gem_result = AnalysisResult(
            risk_score=r["risk_score"] or 0,
            risk_level=gem_level,
            reasons=gem_reasons,
            explanation="",
            confidence=0.9,
            model_version="gemini-3.5-flash-lite"
        )

        # Run actual production heuristics and hybrid synthesis
        heur_result = analyze_with_heuristics(text)
        synth = synthesize_risk(
            original_text=text,
            gemini_result=gem_result,
            heuristic_result=heur_result,
            lang=lang,
            is_obfuscated=False,
            target_model="gemini-3.5-flash-lite"
        )

        pred = synth.risk_level.value
        matrix[gt][pred] += 1
        lang_stats[lang]["total"] += 1
        if gt == pred:
            lang_stats[lang]["correct"] += 1

        if gt == "MEDIUM" and pred == "LOW":
            medium_as_low.append(item_id)

        # Validate anti-hallucination exact substring match
        evidence_matches = []
        for fr in synth.reasons:
            total_evidence_count += 1
            is_exact = fr.evidence in text if fr.evidence else True
            if is_exact:
                exact_evidence_count += 1
            evidence_matches.append(is_exact)

        individual_hybrid_results.append({
            "id": item_id,
            "lang": lang,
            "ground_truth_level": gt,
            "gemini_predicted_level": r["predicted_risk_level"],
            "gemini_risk_score": r["risk_score"],
            "hybrid_predicted_level": pred,
            "hybrid_risk_score": synth.risk_score,
            "hybrid_reasons": [{"code": reas.code, "evidence": reas.evidence} for reas in synth.reasons],
            "evidence_exact_matches": all(evidence_matches) if evidence_matches else True
        })

    # Metrics
    per_class = {}
    for c in classes:
        tp = matrix[c][c]
        fp = sum(matrix[other][c] for other in classes if other != c)
        fn = sum(matrix[c][other] for other in classes if other != c)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        per_class[c] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        }

    macro_f1 = round(sum(per_class[c]["f1"] for c in classes) / 3, 4)
    low_total = sum(matrix["LOW"].values())
    low_fp = matrix["LOW"]["MEDIUM"] + matrix["LOW"]["HIGH"]
    fpr_low = round(low_fp / low_total, 4) if low_total > 0 else 0.0
    ev_rate = round(exact_evidence_count / total_evidence_count, 4) if total_evidence_count > 0 else 1.0

    output = {
        "title": "SafeNet KZ Hybrid Risk Engine Verification (Cached Flash Lite Output)",
        "total_evaluated": len(individual_hybrid_results),
        "confusion_matrix": matrix,
        "per_class_metrics": per_class,
        "macro_f1": macro_f1,
        "false_positive_rate_on_low": fpr_low,
        "evidence_exact_match_rate": ev_rate,
        "medium_classified_as_low_count": len(medium_as_low),
        "medium_as_low_ids": medium_as_low,
        "language_accuracy": {l: round(d["correct"] / d["total"], 4) for l, d in lang_stats.items()},
        "individual_results": individual_hybrid_results
    }

    with open(HYBRID_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("================ HYBRID RISK ENGINE REPORT ================")
    print("Confusion Matrix:")
    print("                 Pred: LOW    MEDIUM      HIGH")
    for actual in classes:
        print(f"  Actual {actual:<6}: {matrix[actual]['LOW']:>7} {matrix[actual]['MEDIUM']:>9} {matrix[actual]['HIGH']:>9}")
    print("\nPer-Class Metrics:")
    for c in classes:
        print(f"  {c:<6} -> Precision: {per_class[c]['precision']}, Recall: {per_class[c]['recall']}, F1: {per_class[c]['f1']}")
    print(f"\nMacro-F1: {macro_f1}")
    print(f"False Positive Rate on LOW: {fpr_low}")
    print(f"Evidence exact match rate: {exact_evidence_count}/{total_evidence_count} ({ev_rate * 100}%)")
    print(f"MEDIUM messages classified as LOW: {len(medium_as_low)} / 10")
    print("===========================================================")

if __name__ == "__main__":
    verify_hybrid()
