"""Pre-registration artifact. Enabled rules come only from a registered hash."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RELEASE_ID = "slip_audit_structural_v1"
STRUCTURAL_DISCLAIMER = (
    "This is a structural observation only. It does not assess correlation, "
    "joint probability, payout adequacy, or whether any selection should be changed."
)

_ARTIFACT = Path(__file__).resolve().parent / "preregistration" / "slip_audit_structural_v1.json"


class RegistryMismatch(RuntimeError):
    """The active registration hash does not match the committed artifact."""


def artifact_path() -> Path:
    return _ARTIFACT


def artifact_bytes() -> bytes:
    return _ARTIFACT.read_bytes()


def artifact_sha256() -> str:
    return hashlib.sha256(artifact_bytes()).hexdigest()


def load_artifact() -> dict:
    payload = json.loads(artifact_bytes().decode("utf-8"))
    if payload.get("release_id") != RELEASE_ID:
        raise RegistryMismatch("pre-registration release id mismatch")
    if payload.get("structural_disclaimer") != STRUCTURAL_DISCLAIMER:
        raise RegistryMismatch("structural disclaimer mismatch")
    permissions = payload.get("language_permissions") or {}
    if not isinstance(permissions, dict) or not permissions or any(permissions.values()):
        raise RegistryMismatch("language permissions must all be false")
    enabled = list(payload.get("enabled_rules") or [])
    disabled = list(payload.get("disabled_rules") or [])
    if set(enabled) & set(disabled):
        raise RegistryMismatch("a rule cannot be both enabled and disabled")
    return payload


def require_active_registration(registration: dict | None) -> dict:
    """Refuse to evaluate when the stored registration is missing or stale."""
    artifact = load_artifact()
    digest = artifact_sha256()
    if registration is None or registration.get("artifact_sha256") != digest:
        raise RegistryMismatch(
            "active registry does not match the registered hash"
        )
    if registration.get("release_id") != artifact["release_id"]:
        raise RegistryMismatch("active registry release id mismatch")
    return artifact
