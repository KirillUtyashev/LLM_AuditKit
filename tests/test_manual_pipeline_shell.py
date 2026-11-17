"""The manual launcher delegates only; these tests never contact providers."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tests/manual/newspaper_pipeline/run.sh"


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout with spaces"
    directory = root / "tests/manual/newspaper_pipeline"
    directory.mkdir(parents=True)
    script = directory / "run.sh"
    shutil.copyfile(LAUNCHER, script)
    script.chmod(0o755)
    capture = tmp_path / "invocation.json"
    environment = os.environ.copy()
    environment["MANUAL_LAUNCHER_CAPTURE"] = str(capture)
    return root, script, capture, environment


def fake_python(root):
    executable = root / ".venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['MANUAL_LAUNCHER_CAPTURE']).write_text(\n"
        "    json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n"
        "raise SystemExit(int(os.environ.get('MANUAL_LAUNCHER_EXIT', '0')))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)


@pytest.mark.parametrize("arguments,expected", [
    ([], ["--run"]),
    (["--check"], ["--check"]),
    (["--phase", "population"], ["--phase", "population"]),
    (["--help"], ["--help"]),
])
def test_uses_checkout_venv_and_forwards_mode_from_any_directory(checkout, tmp_path, arguments, expected):
    root, script, capture, environment = checkout
    fake_python(root)
    result = subprocess.run(["bash", str(script), *arguments], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(capture.read_text()) == {
        "cwd": str(root),
        "args": ["-u", str(root / "scripts/run_pipeline.py"),
                 "--config", str(script.parent / "pipeline.yaml"), *expected],
    }


def test_preserves_runner_failure_exit_status(checkout, tmp_path):
    root, script, capture, environment = checkout
    fake_python(root)
    environment["MANUAL_LAUNCHER_EXIT"] = "7"
    result = subprocess.run(["bash", str(script)], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 7


def test_python3_fallback_without_checkout_venv(checkout, tmp_path):
    root, script, capture, environment = checkout
    (root / "scripts").mkdir()
    (root / "scripts/run_pipeline.py").write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "Path(os.environ['MANUAL_LAUNCHER_CAPTURE']).write_text(\n"
        "    json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    result = subprocess.run(["bash", str(script), "--check"], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(capture.read_text()) == {
        "cwd": str(root), "args": ["--config", str(script.parent / "pipeline.yaml"), "--check"],
    }


def test_ignore_rules_keep_manual_inputs_and_outputs_private(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Git is required to check repository ignore rules")
    shutil.copyfile(ROOT / ".gitignore", tmp_path / ".gitignore")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    base = "tests/manual/newspaper_pipeline/local/chicago-1950-smoke/"
    fixture = base + "source/chicago-daily-tribune-1950-04-02-page-a6.pdf"
    ignored = [
        fixture,
        base + "templates-gpt55-medium-parts.csv", base + "regression_ready.csv",
        base + "candidates.csv", base + "ocr-checkpoints-v3/page.json",
        base + "source/unrelated.pdf",
        "tests/manual/newspaper_pipeline/local/omaha-1900-smoke/source.pdf", ".env",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=tmp_path, input="\n".join(ignored) + "\n",
        text=True, capture_output=True, check=True,
    )
    assert result.stdout.splitlines() == ignored
