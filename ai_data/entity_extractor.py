"""
Entity extraction module for SafeNet KZ.
Identifies financial, contact, and network entities in messages:
- Phone numbers (Kaspi P2P, WhatsApp)
- Bank cards (Kaspi Gold, Halyk, etc.)
- Telegram handles & invite URLs
- WhatsApp group invite links
- Crypto wallet addresses (USDT TRC-20, BTC, ETH)
"""
import re
from typing import List, Dict, Any


def extract_entities(text: str) -> List[Dict[str, str]]:
    """
    Extracts structured entities from message text for link analysis.
    Returns list of dicts: [{"type": "PHONE"|"CARD"|"URL"|"TELEGRAM_USER"|"CRYPTO_WALLET", "value": "..."}]
    """
    if not text:
        return []

    entities = []
    seen = set()

    def _add(etype: str, val: str):
        norm = val.strip()
        key = (etype, norm.lower())
        if key not in seen and len(norm) >= 3:
            seen.add(key)
            entities.append({"type": etype, "value": norm})

    # 1. Phone numbers (Kazakhstan: +7 7xx, 8 7xx)
    phone_pattern = r"(?:\+?7|8)[\s\-\(]*7\d{2}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    for match in re.finditer(phone_pattern, text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith(("77", "87")):
            normalized_phone = "+7" + digits[1:]
            _add("PHONE", normalized_phone)

    # 2. Bank card numbers (16 digits or 4x4 format)
    card_pattern = r"\b(?:\d{4}[\s\-]?){4}\b"
    for match in re.finditer(card_pattern, text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 16:
            # Mask middle digits for privacy: 4400 **** **** 1234
            masked = f"{digits[:4]} **** **** {digits[-4:]}"
            _add("CARD", masked)

    # 3. Telegram channels / users (@username)
    tg_pattern = r"(?<!\w)@[A-Za-z0-9_]{4,32}\b"
    for match in re.finditer(tg_pattern, text):
        _add("TELEGRAM_USER", match.group(0))

    # 4. URLs & Invite links (Telegram & WhatsApp)
    url_pattern = r"https?://(?:t\.me/[A-Za-z0-9_+]{3,64}|chat\.whatsapp\.com/[A-Za-z0-9]{10,32})"
    for match in re.finditer(url_pattern, text):
        _add("URL", match.group(0))

    # 5. Crypto addresses (TRC-20 USDT starts with T and 34 chars)
    crypto_pattern = r"\bT[A-Za-z0-9]{33}\b"
    for match in re.finditer(crypto_pattern, text):
        _add("CRYPTO_WALLET", match.group(0))

    return entities
