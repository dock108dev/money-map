from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


class SecretStoreError(RuntimeError):
    """A safe, non-secret-bearing Keychain failure."""


class SecretStore(Protocol):
    def get(self, namespace: str, key: str) -> str | None: ...

    def set(self, namespace: str, key: str, value: str) -> None: ...

    def delete(self, namespace: str, key: str) -> None: ...


@dataclass(frozen=True)
class MacOSKeychainSecretStore:
    """Versioned desktop Keychain namespace with exact service and account shapes."""

    service_prefix: str = "com.moneymap.desktop.secrets.v1"

    _CONFIG_KEYS = frozenset(
        {
            "sandbox.client_id",
            "sandbox.secret",
            "production.client_id",
            "production.secret",
            "client_user_id",
        }
    )
    _ITEM_KEY = re.compile(r"^(sandbox|production)\.[A-Za-z0-9_-]{1,128}$")

    def _service(self, namespace: str) -> str:
        if namespace not in {"plaid.config", "plaid.items", "slice4.acceptance", "test"}:
            raise SecretStoreError("The Keychain namespace was rejected")
        return f"{self.service_prefix}.{namespace}"

    def _account(self, namespace: str, key: str) -> str:
        valid = (
            (namespace == "plaid.config" and key in self._CONFIG_KEYS)
            or (namespace == "plaid.items" and bool(self._ITEM_KEY.fullmatch(key)))
            or (
                namespace in {"slice4.acceptance", "test"}
                and bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", key))
            )
        )
        if not valid:
            raise SecretStoreError("The Keychain account key was rejected")
        return key

    def get(self, namespace: str, key: str) -> str | None:
        try:
            return keyring.get_password(self._service(namespace), self._account(namespace, key))
        except KeyringError as exc:
            raise SecretStoreError("macOS Keychain could not read the requested secret") from exc

    def set(self, namespace: str, key: str, value: str) -> None:
        if not value:
            raise SecretStoreError("An empty secret cannot be stored")
        try:
            keyring.set_password(self._service(namespace), self._account(namespace, key), value)
        except KeyringError as exc:
            raise SecretStoreError("macOS Keychain could not store the requested secret") from exc

    def delete(self, namespace: str, key: str) -> None:
        try:
            keyring.delete_password(self._service(namespace), self._account(namespace, key))
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise SecretStoreError("macOS Keychain could not delete the requested secret") from exc


@dataclass
class MemorySecretStore:
    """Test-only in-memory implementation."""

    values: dict[tuple[str, str], str] = field(default_factory=dict)

    def get(self, namespace: str, key: str) -> str | None:
        return self.values.get((namespace, key))

    def set(self, namespace: str, key: str, value: str) -> None:
        self.values[(namespace, key)] = value

    def delete(self, namespace: str, key: str) -> None:
        self.values.pop((namespace, key), None)


keychain = MacOSKeychainSecretStore()
