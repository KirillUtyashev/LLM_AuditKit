#!/usr/bin/env python3
"""Clone or update the pinned paper reference implementation."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "references" / "job_parsing-code.json"
REFERENCES_ROOT = (REPOSITORY_ROOT / ".references").resolve()


class SyncError(RuntimeError):
    """Raised when the reference checkout cannot be updated safely."""


def run_git(*arguments: str, cwd: Path | None = None, capture: bool = False) -> str:
    """Run Git and optionally return its standard output."""
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def load_manifest() -> dict[str, str]:
    """Load and validate the fields used by the sync workflow."""
    raw: Any = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SyncError(f"Expected a JSON object in {MANIFEST_PATH}")

    required = ("name", "repository", "revision", "checkout_path")
    missing = [key for key in required if not isinstance(raw.get(key), str) or not raw[key]]
    if missing:
        raise SyncError(f"Missing or invalid manifest fields: {', '.join(missing)}")

    if re.fullmatch(r"[0-9a-f]{40}", raw["revision"]) is None:
        raise SyncError("revision must be a full, lowercase Git commit SHA")

    return {key: raw[key] for key in required}


def resolve_checkout(relative_path: str) -> Path:
    """Resolve the checkout and keep it inside the ignored references directory."""
    checkout = (REPOSITORY_ROOT / relative_path).resolve()
    if checkout == REFERENCES_ROOT or REFERENCES_ROOT not in checkout.parents:
        raise SyncError("checkout_path must point below .references/")
    return checkout


def ensure_clean_checkout(checkout: Path) -> None:
    """Refuse to replace uncommitted work in an existing checkout."""
    if not (checkout / ".git").exists():
        raise SyncError(f"Existing path is not a Git checkout: {checkout}")
    if run_git("status", "--porcelain", cwd=checkout, capture=True):
        raise SyncError(f"Reference checkout has local changes: {checkout}")


def sync_reference() -> tuple[Path, str]:
    """Clone the configured repository and check out its pinned revision."""
    manifest = load_manifest()
    checkout = resolve_checkout(manifest["checkout_path"])
    repository = manifest["repository"]
    revision = manifest["revision"]

    if checkout.exists():
        ensure_clean_checkout(checkout)
        actual_origin = run_git("remote", "get-url", "origin", cwd=checkout, capture=True)
        if actual_origin != repository:
            raise SyncError(
                "Reference checkout origin does not match the manifest: "
                f"expected {repository}, found {actual_origin}"
            )
    else:
        checkout.parent.mkdir(parents=True, exist_ok=True)
        run_git("clone", "--filter=blob:none", "--no-checkout", repository, str(checkout))

    run_git("fetch", "--depth", "1", "origin", revision, cwd=checkout)
    run_git("checkout", "--detach", revision, cwd=checkout)
    resolved_revision = run_git("rev-parse", "HEAD", cwd=checkout, capture=True)
    if resolved_revision != revision:
        raise SyncError(
            f"Expected revision {revision}, but Git checked out {resolved_revision}"
        )

    return checkout, resolved_revision


def main() -> int:
    """Run the sync operation and provide a concise result."""
    try:
        checkout, revision = sync_reference()
    except (OSError, json.JSONDecodeError, subprocess.CalledProcessError, SyncError) as error:
        print(f"Reference sync failed: {error}", file=sys.stderr)
        return 1

    print(f"Paper reference ready at {checkout}")
    print(f"Pinned revision: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
