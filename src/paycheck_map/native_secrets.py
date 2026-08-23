from __future__ import annotations

import subprocess
import sys


class NativeSecretPromptError(RuntimeError):
    pass


_CLIENT_ID_SCRIPT = (
    'set answer to display dialog "Enter the Plaid client ID." default answer "" '
    'buttons {"Cancel", "Continue"} default button "Continue" cancel button "Cancel" '
    'with title "Money Map Plaid setup"\nreturn text returned of answer'
)

_SECRET_SCRIPT = (
    'set answer to display dialog "Enter the Plaid production secret." default answer "" '
    'hidden answer true buttons {"Cancel", "Save"} default button "Save" '
    'cancel button "Cancel" with title "Money Map Plaid setup"\n'
    "return text returned of answer"
)


def _prompt(script: str) -> str:
    if sys.platform != "darwin":
        raise NativeSecretPromptError("Native secret entry is available only in the macOS app.")
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeSecretPromptError("Native secret entry did not complete.") from exc
    if result.returncode != 0:
        raise NativeSecretPromptError("Plaid setup was cancelled.")
    value = result.stdout.rstrip("\r\n")
    if not 8 <= len(value) <= 256 or any(ord(char) < 32 for char in value):
        raise NativeSecretPromptError("The Plaid credential was not accepted.")
    return value


def request_plaid_credentials() -> tuple[str, str]:
    """Collect credentials without command arguments, environment variables, or WebView state."""
    client_id = _prompt(_CLIENT_ID_SCRIPT)
    secret = _prompt(_SECRET_SCRIPT)
    return client_id, secret
