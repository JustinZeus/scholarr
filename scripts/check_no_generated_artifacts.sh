#!/usr/bin/env bash
set -euo pipefail

blocked_regexes=(
  '(^|/)__pycache__/'
  '\\.py[co]$'
  '(^|/)\\.pytest_cache(/|$)'
  '(^|/)\\.mypy_cache(/|$)'
  '(^|/)\\.ruff_cache(/|$)'
  '(^|/)\\.coverage$'
  '(^|/)htmlcov(/|$)'
  '(^|/)(dist|build)(/|$)'
  '(^|/)frontend/(dist|node_modules|\\.vite)(/|$)'
  '(^|/)[^/]+\\.egg-info(/|$)'
  '(^|/)\\.DS_Store$'
  '(^|/)planning(/|$)'
)

tracked_files=()
while IFS= read -r path; do
  tracked_files+=("$path")
done < <(git ls-files)

offenders=()
for path in "${tracked_files[@]}"; do
  for regex in "${blocked_regexes[@]}"; do
    if [[ "$path" =~ $regex ]]; then
      offenders+=("$path")
      break
    fi
  done
done

if (( ${#offenders[@]} > 0 )); then
  {
    echo "Tracked generated artifacts detected (remove from git tracking):"
    printf ' - %s\n' "${offenders[@]}"
  } >&2
  exit 1
fi

echo "Generated artifact guard passed (no tracked cache/build/probe files)."
