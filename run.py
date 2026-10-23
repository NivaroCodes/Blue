#!/usr/bin/env python3
"""
SafeNet KZ — Unified Control CLI for Data / AI Module

Usage:
    python run.py api       Start the FastAPI backend server (http://127.0.0.1:8000)
    python run.py worker    Start the AI Background Worker (processes PENDING messages from DB)
    python run.py seed      Seed the database with 20 realistic test messages
    python run.py test      Run all unit tests
    python run.py eval      Run evaluation benchmark on the 50-sample dataset
"""
import sys
import os

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "api":
        import uvicorn
        print("Starting SafeNet KZ Backend API server on http://127.0.0.1:8000 ...")
        uvicorn.run("ai_data.api_server:app", host="127.0.0.1", port=8000, reload=True)

    elif command == "worker":
        from ai_data.worker import run_worker_loop
        print("Starting SafeNet KZ AI Background Worker ...")
        run_worker_loop()

    elif command == "seed":
        from ai_data.db.seed import seed_database
        print("Seeding database with realistic scenarios ...")
        seed_database()

    elif command == "test":
        import unittest
        print("Running all Data / AI unit tests ...")
        loader = unittest.TestLoader()
        suite = loader.discover("ai_data/tests")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)

    elif command == "eval":
        from ai_data.evaluation.evaluate import run_evaluation, generate_markdown_report
        from pathlib import Path
        import json
        print("Running benchmark evaluation on dataset ...")
        try:
            report = run_evaluation()
            out_dir = Path("ai_data/evaluation")
            json_path = out_dir / "evaluation_report.json"
            md_path = out_dir / "evaluation_report.md"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            generate_markdown_report(report, md_path)
            print(f"Evaluation report updated: {md_path}")
        except Exception as e:
            print(f"Evaluation error: {e}")
            print("Note: To run evaluation with live LLM, make sure GEMINI_API_KEY or OPENAI_API_KEY is set in .env")

    else:
        print(f"Unknown command: '{command}'")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
