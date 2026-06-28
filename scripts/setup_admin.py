"""
One-time admin setup script.

Run from the nse_dashboard project root:
    python scripts/setup_admin.py

What it does:
  1. Prompts for a new admin password (input is hidden)
  2. Generates a bcrypt hash (cost factor 12 — ~250ms per verify, brute-force resistant)
  3. Generates a 32-byte random secret key for HMAC session tokens
  4. Appends [admin] section to .streamlit/secrets.toml

secrets.toml is gitignored — these values never reach GitHub.
Without this file on a cloned repo, all admin features are silently disabled.
"""
import getpass
import pathlib
import secrets
import sys

try:
    import bcrypt
except ImportError:
    sys.exit("ERROR: bcrypt not installed. Run: pip install bcrypt")

_SECRETS_PATH = pathlib.Path(".streamlit/secrets.toml")


def main():
    print("=== NSE Dashboard — Admin Setup ===\n")

    if not _SECRETS_PATH.exists():
        _SECRETS_PATH.parent.mkdir(exist_ok=True)
        _SECRETS_PATH.touch()
        print(f"Created {_SECRETS_PATH}")

    existing = _SECRETS_PATH.read_text(encoding="utf-8")
    if "[admin]" in existing:
        overwrite = input("[admin] section already exists in secrets.toml. Overwrite? (y/N): ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            return

    pwd1 = getpass.getpass("Enter new admin password: ")
    if len(pwd1) < 8:
        sys.exit("ERROR: Password must be at least 8 characters.")
    pwd2 = getpass.getpass("Confirm password: ")
    if pwd1 != pwd2:
        sys.exit("ERROR: Passwords do not match.")

    print("\nGenerating bcrypt hash (this takes ~1 second)...")
    pw_hash    = bcrypt.hashpw(pwd1.encode(), bcrypt.gensalt(rounds=12)).decode()
    secret_key = secrets.token_hex(32)

    # Remove existing [admin] block if present, then append fresh one
    lines = existing.splitlines()
    clean_lines = []
    in_admin = False
    for line in lines:
        if line.strip() == "[admin]":
            in_admin = True
            continue
        if in_admin and line.startswith("["):
            in_admin = False
        if not in_admin:
            clean_lines.append(line)

    new_content = "\n".join(clean_lines).rstrip()
    new_content += f'\n\n[admin]\npassword_hash = "{pw_hash}"\nsecret_key    = "{secret_key}"\n'
    _SECRETS_PATH.write_text(new_content, encoding="utf-8")

    print(f"\n[admin] section written to {_SECRETS_PATH}")
    print("Setup complete. Admin login is now active on the dashboard.")
    print("\nIMPORTANT: secrets.toml is gitignored — never commit it to version control.")


if __name__ == "__main__":
    main()
