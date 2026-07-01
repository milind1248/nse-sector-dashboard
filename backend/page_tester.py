"""
Page-level test suite using Streamlit's AppTest framework.

Each entry in PAGE_REGISTRY is one page to test. To add a new page:
  1. Append one dict to PAGE_REGISTRY below.
  2. No other changes needed.

run_page_tests(base_dir) → list[dict]
  - Sets NSE_TESTING=1 so enforce_deployment_gate() is bypassed.
  - Runs each page via AppTest (in-process, no browser needed).
  - All st.tabs() content is rendered in a single .run() call.
  - Collects st.exception and st.error occurrences.
  - Returns per-page result dicts compatible with page_test_db.store_test_results().
"""
import os
import time
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# ── Page Registry ─────────────────────────────────────────────────────────────
# tabs  : number of st.tabs() tabs on the page (for reporting only)
# timeout: seconds to wait for the page to render (cpu-heavy pages need more)
PAGE_REGISTRY: list[dict] = [
    {"name": "Home",             "file": "app/Home.py",                        "tabs": 3,  "timeout": 25},
    {"name": "Market Pulse",     "file": "app/pages/1_📡_Market_Pulse.py",     "tabs": 0,  "timeout": 45},
    {"name": "Sector Analysis",  "file": "app/pages/2_📈_Sector_Analysis.py",  "tabs": 4,  "timeout": 30},
    {"name": "Index Stocks",     "file": "app/pages/3_🏛️_Index_Stocks.py",    "tabs": 3,  "timeout": 30},
    {"name": "FII DII Flow",     "file": "app/pages/4_🏦_FII_DII_Flow.py",     "tabs": 2,  "timeout": 20},
    {"name": "FII Sectors",      "file": "app/pages/5_🏢_FII_Sectors.py",      "tabs": 2,  "timeout": 20},
    {"name": "FPI Sectors",      "file": "app/pages/6_🌏_FPI_Sectors.py",      "tabs": 6,  "timeout": 20},
    {"name": "Stock Picker",     "file": "app/pages/7_🎯_Stock_Picker.py",     "tabs": 2,  "timeout": 30},
    {"name": "Smart Money",      "file": "app/pages/8_💰_Smart_Money.py",      "tabs": 3,  "timeout": 40},
    {"name": "FII Accumulation", "file": "app/pages/9_📊_FII_Accumulation.py", "tabs": 0,  "timeout": 30},
    {"name": "Alerts",           "file": "app/pages/10_🔔_Alerts.py",          "tabs": 3,  "timeout": 180},
    {"name": "AI Forecast",      "file": "app/pages/11_🤖_AI_Forecast.py",     "tabs": 0,  "timeout": 30},
    {"name": "Gann Analysis",    "file": "app/pages/12_🔢_Gann_Analysis.py",   "tabs": 0,  "timeout": 20},
    {"name": "Export",           "file": "app/pages/13_📤_Export.py",          "tabs": 0,  "timeout": 20},
    {"name": "Contact",          "file": "app/pages/14_📧_Contact.py",         "tabs": 0,  "timeout": 15},
    {"name": "Disclaimer",       "file": "app/pages/15_⚖️_Disclaimer.py",     "tabs": 0,  "timeout": 15},
    # Admin (16_🔐_Admin.py) excluded — it's the test runner itself
]

# Dummy secrets used during testing so is_admin() / verify_password() don't crash.
# These are NOT real credentials — they only prevent import-time errors.
_DUMMY_SK   = "0" * 64                                        # 32-byte hex, all zeros
_DUMMY_HASH = "$2b$12$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # invalid but parseable


def _test_secrets() -> dict:
    return {
        "deploy": {"license_key": "test-bypass"},
        "admin":  {"password_hash": _DUMMY_HASH, "secret_key": _DUMMY_SK},
        "contact": {"web3forms_key": ""},
    }


def run_page_tests(base_dir: str) -> list[dict]:
    """
    Test all pages in PAGE_REGISTRY.

    Parameters
    ----------
    base_dir : str
        Absolute path to the nse_dashboard root (contains app/ and backend/).

    Returns
    -------
    list[dict] with keys: page, file, status, elapsed, tabs, errors
      status  : "OK" | "WARN" | "FAIL"
      errors  : list of {type, message}
    """
    from streamlit.testing.v1 import AppTest

    # Signal enforce_deployment_gate() to skip HMAC + host checks
    os.environ["NSE_TESTING"] = "1"

    results: list[dict] = []
    total = len(PAGE_REGISTRY)

    for idx, page in enumerate(PAGE_REGISTRY):
        page_path = Path(base_dir) / page["file"]
        _log.info("[PageTest] [%d/%d] %s …", idx + 1, total, page["name"])

        t0 = time.time()
        errors: list[dict] = []
        status = "OK"

        if not page_path.exists():
            errors.append({"type": "FileNotFoundError",
                           "message": f"File not found: {page['file']}"})
            results.append({
                "page":    page["name"],
                "file":    page["file"],
                "status":  "FAIL",
                "elapsed": round(time.time() - t0, 2),
                "tabs":    page.get("tabs", 0),
                "errors":  errors,
            })
            _log.warning("[PageTest] %s — file not found", page["name"])
            continue

        try:
            at = AppTest.from_file(str(page_path), default_timeout=page["timeout"])
            # Inject mock secrets so deployment gate and auth imports don't raise
            for section, vals in _test_secrets().items():
                at.secrets[section] = vals

            at.run()

            # Uncaught exceptions (Python tracebacks shown as red box in browser)
            for exc in at.exception:
                errors.append({"type": "Exception", "message": str(exc)})
                status = "FAIL"

            # st.error() calls (explicit error messages from page code)
            for err in at.error:
                errors.append({"type": "st.error", "message": str(err.value)})
                if status != "FAIL":
                    status = "WARN"

        except Exception as e:
            errors.append({"type": "RunError", "message": str(e)})
            status = "FAIL"

        elapsed = round(time.time() - t0, 2)
        results.append({
            "page":    page["name"],
            "file":    page["file"],
            "status":  status,
            "elapsed": elapsed,
            "tabs":    page.get("tabs", 0),
            "errors":  errors,
        })

        icon = "✅" if status == "OK" else ("⚠️" if status == "WARN" else "❌")
        _log.info(
            "[PageTest] %s %s — %.1fs | %d error(s)",
            icon, page["name"], elapsed, len(errors),
        )

    # Always clear the test bypass env var, even if something above raised
    os.environ.pop("NSE_TESTING", None)

    ok   = sum(1 for r in results if r["status"] == "OK")
    warn = sum(1 for r in results if r["status"] == "WARN")
    fail = sum(1 for r in results if r["status"] == "FAIL")
    _log.info(
        "[PageTest] Complete — %d OK  %d WARN  %d FAIL  (of %d pages)",
        ok, warn, fail, total,
    )
    return results
