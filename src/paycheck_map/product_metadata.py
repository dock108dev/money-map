"""Authoritative Python product and schema identity."""

PUBLIC_VERSION = "3.0.0-beta.1"
PYTHON_PACKAGE_VERSION = "3.0.0b1"
SCHEMA_HEAD = "0009_goal_persistence"


def desktop_artifact_name() -> str:
    """Return the release artifact name derived from the public version."""

    return f"Money Map-{PUBLIC_VERSION}-arm64.dmg"
