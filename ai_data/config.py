import os
from typing import Optional
from dotenv import load_dotenv

# Per-machine credentials belong in the ignored .env.local file. Keep the existing
# .env values (database URL, model settings, etc.) as fallbacks.
load_dotenv(".env.local", override=True)
load_dotenv(".env", override=False)

# Model and API Configuration
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "gemini").lower()
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY")
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME: str = os.getenv("AI_MODEL_NAME", "gemini-3-flash-preview")

# Risk Thresholds conforming to SafeNet KZ MVP Contract
LOW_RISK_THRESHOLD: int = 30       # 0 - 29: LOW
HIGH_RISK_THRESHOLD: int = 60      # 60 - 100: HIGH; 30 - 59: MEDIUM

# Model Version identifier
ANALYZER_VERSION: str = "safenet-analyzer-v1.0"
