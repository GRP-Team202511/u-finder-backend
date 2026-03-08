"""
Manual 2FA flow test script.

Tests the full 2FA lifecycle against a running server:
  1. Login (get auth token)
  2. Setup 2FA                → totp_uri, qr_code_base64, backup_codes
  3. Confirm 2FA (with real TOTP code)
  4. Logout & re-login        → requires_2fa=True, temp_token
  5. Verify 2FA (with real TOTP code) → final token
  6. Check 2FA status
  7. Regenerate backup codes
  8. Disable 2FA

Usage:
    # 1. Make sure the server + DB + Redis are running
    # 2. Update EMAIL / PASSWORD below with an existing test account
    # 3. Run:
    python scripts/test_2fa_manual.py
"""
import sys
import time
import requests
import pyotp

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
EMAIL = "test@example.com"       # ← change to a real test account
PASSWORD = "Password1"            # ← change to match

# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def _fail(msg: str):
    print(f"\n✗ FAILED: {msg}")
    sys.exit(1)


def _ok(step: str):
    print(f"  ✓ {step}")


# ── Steps ─────────────────────────────────────────────────────────────────────

def step_login() -> str:
    """Login and return the auth token."""
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 202:
        _fail("Account already has 2FA enabled – disable it first or use a fresh account")
    if r.status_code != 200:
        _fail(f"Login failed ({r.status_code}): {r.text}")
    body = r.json()
    token = body["token"]
    _ok(f"Login succeeded (user_id={body['id']})")
    return token


def step_setup(token: str) -> tuple[str, list[str]]:
    """Setup 2FA, return (totp_secret_from_uri, backup_codes)."""
    r = requests.post(f"{BASE_URL}/auth/2fa/setup", headers=_headers(token))
    if r.status_code != 200:
        _fail(f"Setup failed ({r.status_code}): {r.text}")
    body = r.json()
    totp_uri = body["totp_uri"]
    backup_codes = body["backup_codes"]
    # Extract secret from otpauth URI
    secret = pyotp.parse_uri(totp_uri).secret
    _ok(f"Setup succeeded – secret={secret}, {len(backup_codes)} backup codes")
    return secret, backup_codes


def step_confirm(token: str, secret: str):
    """Confirm 2FA with a real TOTP code."""
    code = pyotp.TOTP(secret).now()
    r = requests.post(f"{BASE_URL}/auth/2fa/confirm", headers=_headers(token), json={"code": code})
    if r.status_code != 200:
        _fail(f"Confirm failed ({r.status_code}): {r.text}")
    _ok(f"Confirm succeeded – 2FA is now enabled (code used: {code})")


def step_login_with_2fa(secret: str) -> str:
    """Login again (should require 2FA), then verify → return final token."""
    # Login → expect 202 (2FA required)
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 202:
        _fail(f"Re-login expected 202, got {r.status_code}: {r.text}")
    body = r.json()
    temp_token = body["temp_token"]
    _ok(f"Re-login returned 202, temp_token received")

    # Wait a moment so TOTP code may advance past the one used in confirm
    time.sleep(1)

    # Verify 2FA
    code = pyotp.TOTP(secret).now()
    r = requests.post(
        f"{BASE_URL}/auth/2fa/verify",
        headers={"Temp-Token": temp_token},
        json={"code": code},
    )
    if r.status_code != 200:
        _fail(f"Verify failed ({r.status_code}): {r.text}")
    body = r.json()
    final_token = body["token"]
    _ok(f"Verify succeeded – final token received (user_id={body['id']})")
    return final_token


def step_verify_backup_code(backup_codes: list[str]) -> str:
    """Login again, then verify using a backup code → return final token."""
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 202:
        _fail(f"Re-login for backup code test expected 202, got {r.status_code}: {r.text}")
    body = r.json()
    temp_token = body["temp_token"]

    code = backup_codes[0]
    r = requests.post(
        f"{BASE_URL}/auth/2fa/verify",
        headers={"Temp-Token": temp_token},
        json={"code": code},
    )
    if r.status_code != 200:
        _fail(f"Backup code verify failed ({r.status_code}): {r.text}")
    body = r.json()
    _ok(f"Backup code verify succeeded (code={code}, user_id={body['id']})")
    return body["token"]


def step_status(token: str):
    """Check 2FA status."""
    r = requests.get(f"{BASE_URL}/auth/2fa/status", headers=_headers(token))
    if r.status_code != 200:
        _fail(f"Status failed ({r.status_code}): {r.text}")
    body = r.json()
    _ok(f"Status: is_2fa_enabled={body['is_2fa_enabled']}, backup_codes_remaining={body['backup_codes_remaining']}")
    return body


def step_regenerate(token: str, secret: str):
    """Regenerate backup codes."""
    code = pyotp.TOTP(secret).now()
    r = requests.post(
        f"{BASE_URL}/auth/2fa/backup-codes/regenerate",
        headers=_headers(token),
        json={"code": code},
    )
    if r.status_code != 200:
        _fail(f"Regenerate failed ({r.status_code}): {r.text}")
    body = r.json()
    _ok(f"Regenerated {len(body['backup_codes'])} backup codes")


def step_disable(token: str):
    """Disable 2FA."""
    r = requests.post(
        f"{BASE_URL}/auth/2fa/disable",
        headers=_headers(token),
        json={"password": PASSWORD},
    )
    if r.status_code != 200:
        _fail(f"Disable failed ({r.status_code}): {r.text}")
    _ok("2FA disabled successfully")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  2FA Full Flow Manual Test")
    print("=" * 60)

    print("\n[1/8] Login")
    token = step_login()

    print("\n[2/8] Setup 2FA")
    secret, backup_codes = step_setup(token)

    print("\n[3/8] Confirm 2FA")
    step_confirm(token, secret)

    print("\n[4/8] Login with 2FA (TOTP code)")
    token = step_login_with_2fa(secret)

    print("\n[5/8] Check 2FA status")
    status = step_status(token)
    assert status["is_2fa_enabled"] is True
    # No backup code used yet, so all 8 should remain
    assert status["backup_codes_remaining"] == 8

    print("\n[6/8] Verify with backup code")
    token = step_verify_backup_code(backup_codes)

    print("\n[7/8] Regenerate backup codes")
    step_regenerate(token, secret)

    print("\n[8/8] Disable 2FA")
    step_disable(token)

    print("\n" + "=" * 60)
    print("  ALL STEPS PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
