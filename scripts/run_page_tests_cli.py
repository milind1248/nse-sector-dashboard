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

    import os, time
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from backend.page_tester import PAGE_REGISTRY, _test_secrets
    from app.utils.page_test_db import store_test_results

    os.environ["NSE_TESTING"] = "1"
    results = []
    total = len(PAGE_REGISTRY)

    for idx, page in enumerate(PAGE_REGISTRY):
        page_path = Path(ROOT) / page["file"]
        t0 = time.time()
        errors = []
        status = "OK"

        if not page_path.exists():
            errors.append({"type": "FileNotFoundError",
                           "message": f"File not found: {page['file']}"})
            status = "FAIL"
        else:
            try:
                at = AppTest.from_file(str(page_path))
                for section, vals in _test_secrets().items():
                    at.secrets[section] = vals
                at.run(timeout=page["timeout"])
                for exc in at.exception:
                    errors.append({"type": "Exception", "message": str(exc)})
                    status = "FAIL"
                for err in at.error:
                    errors.append({"type": "st.error", "message": str(err.value)})
                    if status != "FAIL":
                        status = "WARN"
            except Exception as e:
                errors.append({"type": "RunError", "message": str(e)})
                status = "FAIL"

        elapsed = round(time.time() - t0, 2)
        results.append({
            "page": page["name"], "file": page["file"],
            "status": status, "elapsed": elapsed,
            "tabs": page.get("tabs", 0), "errors": errors,
        })
        # Print after each page so Admin page can show live progress
        icon = "OK" if status == "OK" else ("WARN" if status == "WARN" else "FAIL")
        print(f"PAGE:{idx+1}:{total}:{page['name']}:{icon}:{elapsed}", flush=True)

    os.environ.pop("NSE_TESTING", None)
    store_test_results(run_id=run_id, results=results)

    ok   = sum(1 for r in results if r["status"] == "OK")
    warn = sum(1 for r in results if r["status"] == "WARN")
    fail = sum(1 for r in results if r["status"] == "FAIL")
    print(f"DONE:{ok}:{warn}:{fail}:{total}", flush=True)


if __name__ == "__main__":
    main()
