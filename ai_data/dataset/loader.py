import json
from pathlib import Path
from typing import List, Dict, Any


DATASET_PATH = Path(__file__).parent / "benchmark_data.json"


def load_benchmark_dataset() -> List[Dict[str, Any]]:
    """
    Loads the gold-standard benchmark evaluation dataset.
    """
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_dataset_statistics() -> Dict[str, Any]:
    """
    Returns summary statistics about the dataset.
    """
    data = load_benchmark_dataset()
    total = len(data)
    by_level = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_lang = {}
    by_category = {}
    pyramid_count = 0

    for item in data:
        level = item.get("expected_level", "LOW")
        by_level[level] = by_level.get(level, 0) + 1
        
        lang = item.get("language", "other")
        by_lang[lang] = by_lang.get(lang, 0) + 1

        cat = item.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + 1

        if item.get("is_pyramid"):
            pyramid_count += 1

    return {
        "total_samples": total,
        "by_level": by_level,
        "by_language": by_lang,
        "by_category": by_category,
        "pyramid_samples": pyramid_count,
        "benign_samples": total - pyramid_count
    }
