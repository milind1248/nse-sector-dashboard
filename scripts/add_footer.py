"""Append show_footer() to all page files that don't already have it."""
from pathlib import Path

pages_dir = Path(__file__).resolve().parent.parent / "app" / "pages"

IMPORT_LINE = "from app.utils.disclaimer import show_footer"
CALL_LINE   = "show_footer()"
FOOTER_BLOCK = f"\n{IMPORT_LINE}\n{CALL_LINE}\n"

for py in sorted(pages_dir.glob("*.py")):
    text = py.read_text(encoding="utf-8")
    if CALL_LINE in text:
        print(f"SKIP  {py.name} (already has footer)")
        continue
    py.write_text(text.rstrip() + FOOTER_BLOCK, encoding="utf-8")
    print(f"OK    {py.name}")
