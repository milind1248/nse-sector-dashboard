"""Replace 'NSE Sector Analysis' with 'Market Sector Analysis' across all Python files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD  = "NSE Sector Analysis"
NEW  = "Market Sector Analysis"

for py in ROOT.rglob("*.py"):
    if ".git" in py.parts or "scripts" in py.parts:
        continue
    text = py.read_text(encoding="utf-8")
    if OLD in text:
        py.write_text(text.replace(OLD, NEW), encoding="utf-8")
        print(f"OK  {py.relative_to(ROOT)}")
