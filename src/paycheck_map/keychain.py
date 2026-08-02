from __future__ import annotations

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
    service_prefix: str = "com.paycheck-map"

    def _service(self, namespace: str) -> str:
        return f"{self.service_prefix}.{namespace}"

    def get(self, namespace: str, key: str) -> str | None:
        try:
            return keyring.get_password(self._service(namespace), key)
        except KeyringError as exc:
            raise SecretStoreError("macOS Keychain could not read the requested secret") from exc

    def set(self, namespace: str, key: str, value: str) -> None:
        if not value:
            raise SecretStoreError("An empty secret cannot be stored")
        try:
            keyring.set_password(self._service(namespace), key, value)
        except KeyringError as exc:
            raise SecretStoreError("macOS Keychain could not store the requested secret") from exc

    def delete(self, namespace: str, key: str) -> None:
        try:
            keyring.delete_password(self._service(namespace), key)
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
