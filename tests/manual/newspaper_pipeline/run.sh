#!/usr/bin/env bash
# Explicitly invoked live smoke test; default execution makes paid API calls.
set -euo pipefail

test_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$test_dir/../../.." && pwd)"

if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_command="$repo_root/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    python_command="$(command -v python3)"
else
    echo "Python is unavailable. Create the repository .venv and install its dependencies." >&2
    exit 1
fi

# The existing runner handles .env, validation, stage APIs and checkpoint resume.
# Do not add another retry loop, cache, or credential loader here.
cd -- "$repo_root"
if [[ $# -eq 0 ]]; then
    set -- --run
fi
exec "$python_command" -u "$repo_root/scripts/run_pipeline.py" \
    --config "$test_dir/pipeline.yaml" "$@"
