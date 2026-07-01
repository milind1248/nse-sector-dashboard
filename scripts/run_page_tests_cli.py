"""
Standalone CLI runner for page tests.
Called as a subprocess from the Admin page so AppTest runs in its own
Python process — completely isolated from the parent Streamlit runtime.

Usage:
    python scripts/run_page_tests_cli.py <run_id>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def main():
    run_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    from backend.page_tester import run_page_tests
    from app.utils.page_test_db import store_test_results

    results = run_page_tests(str(ROOT))
    store_test_results(run_id=run_id, results=results)

    ok   = sum(1 for r in results if r["status"] == "OK")
    warn = sum(1 for r in results if r["status"] == "WARN")
    fail = sum(1 for r in results if r["status"] == "FAIL")
    print(f"DONE:{ok}:{warn}:{fail}:{len(results)}", flush=True)


if __name__ == "__main__":
    main()
