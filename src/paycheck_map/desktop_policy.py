"""Authoritative Python policy for supported desktop data modes."""

PRODUCTION_DATA_MODE = "production-v1"
ACCEPTANCE_DATA_MODE = "acceptance-synthetic-v1"
KEYCHAIN_ACCEPTANCE_DATA_MODE = "keychain-acceptance-v1"
DISPOSABLE_DATA_MODE = "disposable-synthetic"

MANAGED_DATA_MODES = frozenset(
    {
        PRODUCTION_DATA_MODE,
        ACCEPTANCE_DATA_MODE,
        KEYCHAIN_ACCEPTANCE_DATA_MODE,
    }
)
MEMORY_SECRET_STORE_DATA_MODES = frozenset({ACCEPTANCE_DATA_MODE, KEYCHAIN_ACCEPTANCE_DATA_MODE})


def uses_managed_data_home(mode: str | None) -> bool:
    return mode in MANAGED_DATA_MODES


def uses_memory_secret_store(mode: str | None) -> bool:
    return mode in MEMORY_SECRET_STORE_DATA_MODES
