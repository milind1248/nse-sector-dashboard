"""
Run once to generate the deployment license key from your existing secret_key.
The key is derived from secrets.toml[admin][secret_key] — never stored in source.

Usage:
    python scripts/generate_license_key.py

Then paste the output into:
  1. .streamlit/secrets.toml  (local development)
  2. Streamlit Cloud → App Settings → Secrets  (production)
"""
import hmac
import hashlib
import pathlib

try:
    import toml
except ImportError:
    raise SystemExit("Run: pip install toml")

secrets_path = pathlib.Path(".streamlit/secrets.toml")
if not secrets_path.exists():
    raise SystemExit(f"Not found: {secrets_path}  (run from project root)")

secrets = toml.loads(secrets_path.read_text(encoding="utf-8"))

try:
    secret_key = secrets["admin"]["secret_key"]
except KeyError:
    raise SystemExit("No [admin] secret_key found in secrets.toml. Run scripts/setup_admin.py first.")

license_key = hmac.new(
    bytes.fromhex(secret_key),
    b"marketsector",
    hashlib.sha256,
).hexdigest()

print("\nAdd the following to your secrets.toml AND Streamlit Cloud Secrets dashboard:\n")
print(f'[deploy]')
print(f'license_key = "{license_key}"')
print("\nDone. Never commit secrets.toml to git.")
