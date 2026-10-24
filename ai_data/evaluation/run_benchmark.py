import os
import sys
import json
import time
from typing import Dict, Any, List
from collections import defaultdict

# Add Blue project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
load_dotenv()

from ai_data.llm_client import call_gemini_api, AIAnalysisError

BENCHMARK_PATH = os.path.join(os.path.dirname(__file__), "flash_lite_benchmark.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
EVAL_MODEL = "gemini-3.5-flash-lite"


def calculate_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid_results = [r for r in results if r.get("api_success")]
    if not valid_results:
        return {"error": "No successful API calls to calculate metrics"}

    classes = ["LOW", "MEDIUM", "HIGH"]
    matrix = {actual: {pred: 0 for pred in classes} for actual in classes}

    total_evidence_count = 0
    exact_evidence_count = 0
    valid_json_count = len(valid_results)

    # By language
    lang_stats = defaultdict(lambda: {"total": 0, "correct": 0, "classes": {c: {"tp": 0, "fp": 0, "fn": 0} for c in classes}})

    for r in valid_results:
        actual = r["ground_truth_level"]
        pred = r["predicted_risk_level"]
        lang = r["lang"]

        if actual in matrix and pred in matrix[actual]:
            matrix[actual][pred] += 1

        lang_stats[lang]["total"] += 1
        if actual == pred:
            lang_stats[lang]["correct"] += 1

        # Evidence accuracy
        ev_matches = r.get("evidence_matches", [])
        total_evidence_count += len(ev_matches)
        exact_evidence_count += sum(1 for m in ev_matches if m)

    # Class-level precision, recall, F1
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

    macro_f1 = round(sum(per_class[c]["f1"] for c in classes) / len(classes), 4)

    # FPR on normal messages (LOW classified as MEDIUM or HIGH)
    low_total = sum(matrix["LOW"].values())
    low_fp = matrix["LOW"]["MEDIUM"] + matrix["LOW"]["HIGH"]
    fpr_normal = round(low_fp / low_total, 4) if low_total > 0 else 0.0

    # Evidence match rate
    evidence_match_rate = round(exact_evidence_count / total_evidence_count, 4) if total_evidence_count > 0 else 1.0

    # Accuracy per language
    lang_summary = {}
    for lang, data in lang_stats.items():
        lang_summary[lang] = {
            "total": data["total"],
            "accuracy": round(data["correct"] / data["total"], 4) if data["total"] > 0 else 0.0
        }

    return {
        "total_evaluated": len(valid_results),
        "classes": classes,
        "confusion_matrix": matrix,
        "per_class_metrics": per_class,
        "macro_f1": macro_f1,
        "high_class_metrics": per_class["HIGH"],
        "false_positive_rate_on_low": fpr_normal,
        "valid_json_rate": round(valid_json_count / len(valid_results), 4),
        "evidence_exact_match_rate": evidence_match_rate,
        "language_breakdown": lang_summary
    }


def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set.")
        sys.exit(1)

    with open(BENCHMARK_PATH, "r", encoding="utf-8") as f:
        benchmark_items = json.load(f)

    # Resume from existing results if present to avoid re-sending already tested examples
    existing_results = []
    already_tested_ids = set()
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                existing_results = [r for r in prev_data.get("individual_results", []) if r.get("api_success")]
                already_tested_ids = {r["id"] for r in existing_results}
                print(f"Resuming: found {len(already_tested_ids)} previously completed items.")
        except Exception as e:
            print(f"Could not read existing results: {e}")

    total_count = len(benchmark_items)
    print(f"Loaded {total_count} benchmark items from {BENCHMARK_PATH}")
    print(f"Target Evaluation Model: {EVAL_MODEL}")
    print("Starting/resuming benchmark run...\n")

    results = list(existing_results)
    quota_exhausted = False
    stop_reason = ""

    for idx, item in enumerate(benchmark_items, 1):
        item_id = item["id"]
        if item_id in already_tested_ids:
            continue

        text = item["text"]
        gt_level = item["ground_truth_level"]
        lang = item["lang"]

        print(f"[{idx}/{total_count}] Testing {item_id} ({lang}, GT={gt_level})... ", end="", flush=True)

        t_start = time.monotonic()
        try:
            # Single attempt per benchmark example to adhere to Google API free limits
            res = call_gemini_api(
                text=text,
                api_key=api_key,
                model=EVAL_MODEL,
                max_attempts=1,
                max_total_wait=15.0
            )
            t_elapsed = round(time.monotonic() - t_start, 2)

            predicted_level = res.risk_level.value
            reasons_data = [{"code": r.code, "evidence": r.evidence} for r in res.reasons]

            # Validate evidence matches original text
            evidence_matches = [
                (r.evidence in text) if r.evidence else True
                for r in res.reasons
            ]

            record = {
                "id": item_id,
                "lang": lang,
                "ground_truth_level": gt_level,
                "predicted_risk_level": predicted_level,
                "risk_score": res.risk_score,
                "reasons": reasons_data,
                "evidence_matches": evidence_matches,
                "valid_json": True,
                "execution_time_seconds": t_elapsed,
                "api_success": True,
                "error": None
            }
            results.append(record)
            print(f"OK ({t_elapsed}s) -> Pred={predicted_level} [Score={res.risk_score}]")

        except AIAnalysisError as e:
            t_elapsed = round(time.monotonic() - t_start, 2)
            err_str = str(e)
            print(f"FAILED ({t_elapsed}s): {err_str[:120]}")

            is_quota = "quota" in err_str.lower() or "429" in err_str or "resource_exhausted" in err_str.lower()
            record = {
                "id": item_id,
                "lang": lang,
                "ground_truth_level": gt_level,
                "predicted_risk_level": None,
                "risk_score": None,
                "reasons": [],
                "evidence_matches": [],
                "valid_json": False,
                "execution_time_seconds": t_elapsed,
                "api_success": False,
                "error": err_str
            }
            results.append(record)

            if is_quota:
                quota_exhausted = True
                remaining = total_count - idx
                stop_reason = f"Quota exhausted (429 RESOURCE_EXHAUSTED). Stopping benchmark. Remaining examples: {remaining}"
                print(f"\n[STOP] {stop_reason}")
                break

        except Exception as e:
            t_elapsed = round(time.monotonic() - t_start, 2)
            print(f"UNEXPECTED ERROR ({t_elapsed}s): {type(e).__name__}: {e}")
            record = {
                "id": item_id,
                "lang": lang,
                "ground_truth_level": gt_level,
                "predicted_risk_level": None,
                "risk_score": None,
                "reasons": [],
                "evidence_matches": [],
                "valid_json": False,
                "execution_time_seconds": t_elapsed,
                "api_success": False,
                "error": str(e)
            }
            results.append(record)

        # Rate-limiting pause between requests (4.2s to stay under 15 RPM limit)
        time.sleep(4.2)


    # Compute overall statistics
    metrics = calculate_metrics(results)

    final_payload = {
        "model": EVAL_MODEL,
        "date_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "total_items_in_benchmark": total_count,
        "processed_items_count": len([r for r in results if r.get("api_success")]),
        "quota_exhausted": quota_exhausted,
        "stop_reason": stop_reason if quota_exhausted else None,
        "metrics": metrics,
        "individual_results": results
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, ensure_ascii=False, indent=2)

    print(f"\nSaved complete benchmark results to: {OUTPUT_PATH}")
    print("\n=== SUMMARY METRICS ===")
    if "error" not in metrics:
        print(f"Total Successfully Evaluated: {metrics['total_evaluated']}")
        print(f"Confusion Matrix (Actual x Predicted):")
        for act in metrics["classes"]:
            print(f"  {act:6s}: {metrics['confusion_matrix'][act]}")
        print(f"HIGH Precision: {metrics['high_class_metrics']['precision']}")
        print(f"HIGH Recall:    {metrics['high_class_metrics']['recall']}")
        print(f"HIGH F1:        {metrics['high_class_metrics']['f1']}")
        print(f"Macro-F1:       {metrics['macro_f1']}")
        print(f"FPR on LOW:     {metrics['false_positive_rate_on_low']}")
        print(f"Evidence Exact Match Rate: {metrics['evidence_exact_match_rate'] * 100:.1f}%")
        print("Language Breakdown:")
        for l, d in metrics["language_breakdown"].items():
            print(f"  {l}: Accuracy = {d['accuracy']*100:.1f}% ({d['total']} items)")
    else:
        print(metrics["error"])


if __name__ == "__main__":
    main()
