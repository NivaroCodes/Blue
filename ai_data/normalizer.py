import re
from typing import Tuple, Dict


LEET_MAP: Dict[str, str] = {
    "0": "о",
    "1": "i",
    "3": "з",
    "4": "ч",
    "@": "а",
    "$": "с",
}

# Common transliteration mappings for Kazakh & Russian
TRANSLIT_TO_CYRILLIC: Dict[str, str] = {
    "sh": "ш", "ch": "ч", "zh": "ж", "kh": "х", "ts": "ц", "ya": "я", "yu": "ю",
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е", "z": "з",
    "i": "и", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "r": "р", "s": "с", "t": "т", "u": "у", "f": "ф", "y": "ы"
}

KAZAKH_SPECIFIC_CHARS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")


def detect_language(text: str) -> str:
    """
    Detects whether the text is primarily Kazakh (kz), Russian (ru), or Translit (translit).
    """
    lower = text.lower()
    if any(c in KAZAKH_SPECIFIC_CHARS for c in text):
        return "kz"
    
    kz_common_stems = ["бүгін", "ертең", "ақша", "теңге", "табыс", "кепілдік", "досың", "жарна", "кіру", "аудар", "шақыр"]
    if any(stem in lower for stem in kz_common_stems):
        return "kz"

    # Check for transliterated text
    cyrillic_chars = len(re.findall(r"[\u0400-\u04FF]", text))
    latin_chars = len(re.findall(r"[a-zA-Z]", text))
    
    if latin_chars > 0 and cyrillic_chars < latin_chars:
        return "translit"
    
    return "ru"


def normalize_text_for_search(text: str) -> str:
    """
    Normalizes text for keyword/regex searching while keeping length roughly aligned.
    Replaces leet symbols and standardizes spaces.
    """
    normalized = text.lower()
    # Currency standardization for searching
    normalized = normalized.replace("₸", " тг ").replace("тенге", " тг ").replace("kzt", " тг ")
    
    # Simple leet replacement for letters inside words
    for leet, char in LEET_MAP.items():
        normalized = re.sub(rf"(?<=[a-zA-Zа-яА-Я]){re.escape(leet)}", char, normalized)
        normalized = re.sub(rf"{re.escape(leet)}(?=[a-zA-Zа-яА-Я])", char, normalized)
        
    return normalized


def find_exact_substring(original_text: str, target: str) -> str:
    """
    Ensures the extracted evidence is an EXACT substring of original_text (case-sensitive or insensitive match).
    If an exact match is found (even with different casing), returns the exact slice from original_text.
    If not directly found, returns closest exact slice or empty string.
    """
    if not target or not original_text:
        return ""

    # Direct exact substring
    if target in original_text:
        return target

    # Case-insensitive substring
    lower_orig = original_text.lower()
    lower_target = target.lower().strip()

    pos = lower_orig.find(lower_target)
    if pos != -1:
        return original_text[pos:pos + len(lower_target)]

    # Words-in-sequence match
    words = [re.escape(w) for w in re.split(r"\s+", lower_target) if w]
    if words:
        pattern = r"\s+".join(words)
        match = re.search(pattern, original_text, re.IGNORECASE)
        if match:
            return match.group(0)

    # Substring search by longest matching word chunk
    if len(words) > 2:
        sub_pattern = r"\s+".join(words[:2])
        match = re.search(sub_pattern, original_text, re.IGNORECASE)
        if match:
            return match.group(0)

    return ""
