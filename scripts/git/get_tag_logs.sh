#!/usr/bin/env bash
set -euo pipefail

# 1. Obtener el último tag SemVer anotado (defaults to v0.0.0 if none exists)
LATEST_TAG=$(git describe --tags --match "v[0-9]*.[0-9]*.[0-9]*" --abbrev=0 2>/dev/null || echo "v0.0.0")

CLEAN_VERSION="${LATEST_TAG#v}"
IFS='.' read -r MAJOR MINOR PATCH <<< "$CLEAN_VERSION"

NEXT_PATCH="v${MAJOR}.${MINOR}.$((PATCH + 1))"
NEXT_MINOR="v${MAJOR}.$((MINOR + 1)).0"
NEXT_MAJOR="v$((MAJOR + 1)).0.0"

echo "=== VERSION CONTEXT ==="
echo "CURRENT_TAG: $LATEST_TAG"
echo "SUGGESTED_PATCH: $NEXT_PATCH"
echo "SUGGESTED_MINOR: $NEXT_MINOR"
echo "SUGGESTED_MAJOR: $NEXT_MAJOR"
echo "======================="

# 2. Verificar commits entre 'stable' y 'HEAD'
COMMITS_AHEAD=$(git log stable..HEAD --oneline 2>/dev/null || echo "")

if [[ -n "$COMMITS_AHEAD" ]]; then
  echo "Comparing HEAD against reference: stable"
  echo "--- Commits since 'stable' up to HEAD ---"
  git log "stable..HEAD" --oneline

elif [[ -n "$LATEST_TAG" && "$LATEST_TAG" != "v0.0.0" ]]; then
  echo "HEAD is at 'stable'. Comparing 'stable' against latest tag: $LATEST_TAG"
  echo "--- Commits in current 'stable' release since $LATEST_TAG ---"
  git log "${LATEST_TAG}..stable" --oneline

else
  echo "NO_TAGS_FOUND"
  echo "No previous version tags found in the repository."
fi