"""
Entity extraction module for SafeNet KZ.
Identifies financial, contact, and network entities in messages:
- Phone numbers (Kaspi P2P, WhatsApp)
- Bank cards (Kaspi Gold, Halyk, etc.)
- Telegram handles & invite URLs
- WhatsApp group invite links
- Crypto wallet addresses (USDT TRC-20, BTC, ETH)

Every entity has two values:
- "value":   comparison key used for graph linking (must uniquely identify the real entity)
- "display": privacy-safe, human-readable form shown on the dashboard

Cards are the important case: the masked form "4400 **** **** 1234" is NOT unique — two different
cards with the same first/last four digits would collapse into one node and create a false link
between unrelated authors. The key is therefore a keyed hash (HMAC-SHA256) of the full 16 digits.
"""
import hashlib
import hmac
import os
import re
from typing import List, Dict, Optional

# Secret used to derive card keys. Set ENTITY_HASH_SECRET in .env in production so that
# card keys cannot be brute-forced back to card numbers from a leaked database.
_HASH_SECRET = os.getenv("ENTITY_HASH_SECRET", "safenet-kz-dev-secret").encode("utf-8")


def card_key(digits: str) -> str:
    """Stable, non-reversible identifier of a full 16-digit card number."""
    return "card:" + hmac.new(_HASH_SECRET, digits.encode("ascii"), hashlib.sha256).hexdigest()[:32]


def mask_card(digits: str) -> str:
    """Privacy-safe masked display format keeping BIN prefix and last 4 digits."""
    return f"{digits[:4]} **** **** {digits[-4:]}"


def luhn_valid(digits: str) -> bool:
    """Luhn checksum helper."""
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def extract_entities(text: str) -> List[Dict[str, str]]:
    """
    Extracts structured entities from message text for link analysis.
    Returns list of dicts:
        [{"type": "PHONE"|"CARD"|"URL"|"TELEGRAM_USER"|"CRYPTO_WALLET", "value": <key>, "display": <shown>}]
    """
    if not text:
        return []

    entities: List[Dict[str, str]] = []
    seen = set()

    def _add(etype: str, key: str, display: Optional[str] = None, case_sensitive: bool = False):
        key = key.strip()
        dedup = (etype, key if case_sensitive else key.lower())
        if dedup not in seen and len(key) >= 3:
            seen.add(dedup)
            entities.append({"type": etype, "value": key, "display": (display or key).strip()})

    # 1. Phone numbers (Kazakhstan: +7 7xx, 8 7xx)
    phone_pattern = r"(?<!\d)(?:\+?7|8)[\s\-\(]*7\d{2}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"
    for match in re.finditer(phone_pattern, text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 11 and digits.startswith(("77", "87")):
            _add("PHONE", "+7" + digits[1:])

    # 2. Bank card numbers (16 digits or 4x4 format, not embedded inside IBANs or longer numbers)
    card_pattern = r"(?<![A-Za-z\d])(?:\d{4}[\s\-]?){3}\d{4}(?![A-Za-z\d])"
    for match in re.finditer(card_pattern, text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 16 and len(set(digits)) > 1:
            # Key = HMAC-SHA256 of all 16 digits (no false collisions); display = masked (privacy).
            _add("CARD", card_key(digits), mask_card(digits))

    # 3. Telegram channels / users (@username) — Telegram usernames are case-insensitive
    tg_pattern = r"(?<!\w)@[A-Za-z0-9_]{4,32}\b"
    for match in re.finditer(tg_pattern, text):
        handle = match.group(0)
        _add("TELEGRAM_USER", handle.lower(), handle)

    # 4. URLs & Invite links (Telegram & WhatsApp) — invite tokens are case-sensitive
    url_pattern = r"https?://(?:t\.me/[A-Za-z0-9_+]{3,64}|chat\.whatsapp\.com/[A-Za-z0-9]{10,32})"
    for match in re.finditer(url_pattern, text):
        _add("URL", match.group(0), case_sensitive=True)

    # 5. Crypto addresses (TRC-20 USDT starts with T and 34 chars) — case-sensitive base58
    crypto_pattern = r"\bT[A-Za-z0-9]{33}\b"
    for match in re.finditer(crypto_pattern, text):
        _add("CRYPTO_WALLET", match.group(0), case_sensitive=True)

    return entities
