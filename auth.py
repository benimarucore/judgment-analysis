"""
Secure Authentication Module — No SQL, No Injection Risk.

Credentials are stored as bcrypt-hashed values in a JSON file.
Users can change their credentials through the Settings page.
All password comparisons use bcrypt's constant-time comparison.
"""

import os
import json
import bcrypt

# Credentials file path (next to this script)
CREDENTIALS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "credentials.json"
)


def _hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash (constant-time)."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _load_credentials() -> dict:
    """Load credentials from the JSON file. Creates default if not exists."""
    if not os.path.exists(CREDENTIALS_FILE):
        # Create default credentials: admin / admin123
        default = {
            "admin": {
                "password_hash": _hash_password("admin123"),
                "display_name": "Administrator",
            }
        }
        _save_credentials(default)
        return default

    with open(CREDENTIALS_FILE, "r") as f:
        return json.load(f)


def _save_credentials(creds: dict):
    """Save credentials to the JSON file."""
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(creds, f, indent=2)


def authenticate_user(username: str, password: str) -> bool:
    """
    Authenticate a user by username and password.
    Returns True if credentials match, False otherwise.

    Security: No SQL is involved. Uses bcrypt constant-time comparison.
    Input is never interpolated into any query or command.
    """
    if not username or not password:
        return False

    creds = _load_credentials()
    user = creds.get(username)
    if not user:
        # Still run bcrypt to prevent timing attacks revealing valid usernames
        _verify_password(password, _hash_password("dummy"))
        return False

    return _verify_password(password, user["password_hash"])


def get_display_name(username: str) -> str:
    """Get the display name for a user."""
    creds = _load_credentials()
    user = creds.get(username)
    return user.get("display_name", username) if user else username


def change_password(
    username: str, current_password: str, new_password: str
) -> tuple[bool, str]:
    """
    Change a user's password. Requires current password verification.
    Returns (success: bool, message: str).
    """
    if not current_password or not new_password:
        return False, "All fields are required."

    if len(new_password) < 6:
        return False, "New password must be at least 6 characters."

    creds = _load_credentials()
    user = creds.get(username)
    if not user:
        return False, "User not found."

    if not _verify_password(current_password, user["password_hash"]):
        return False, "Current password is incorrect."

    user["password_hash"] = _hash_password(new_password)
    _save_credentials(creds)
    return True, "Password changed successfully."


def change_username(
    current_username: str, new_username: str, password: str
) -> tuple[bool, str]:
    """
    Change a user's username. Requires password verification.
    Returns (success: bool, message: str).
    """
    if not new_username or not password:
        return False, "All fields are required."

    if len(new_username) < 3:
        return False, "Username must be at least 3 characters."

    creds = _load_credentials()
    user = creds.get(current_username)
    if not user:
        return False, "User not found."

    if not _verify_password(password, user["password_hash"]):
        return False, "Password is incorrect."

    if new_username in creds and new_username != current_username:
        return False, "Username already exists."

    # Remove old username entry, add new one
    creds[new_username] = creds.pop(current_username)
    _save_credentials(creds)
    return True, "Username changed successfully."
