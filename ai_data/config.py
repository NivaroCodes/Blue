import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Mandatory PostgreSQL Configuration (SQLite is forbidden in runtime)
DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

# Google Gemini API Configuration (via Google AI Studio)
# Single model configuration: default gemini-3.5-flash-lite
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY")
MODEL_NAME: str = os.getenv("AI_MODEL_NAME") or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_MODEL: str = MODEL_NAME

# Risk Thresholds conforming to SafeNet KZ MVP Contract
LOW_RISK_THRESHOLD: int = 30       # 0 - 29: LOW
HIGH_RISK_THRESHOLD: int = 60      # 60 - 100: HIGH; 30 - 59: MEDIUM

# Model Version identifier
ANALYZER_VERSION: str = "safenet-analyzer-v1.0"
