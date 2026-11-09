#!/usr/bin/env bash
set -euo pipefail

TYPE="${1:-}"

if [[ -z "$TYPE" ]]; then
  echo "Error: A semantic parameter must be provided."
  echo "Usage: $0 <patch | minor | major | stable>"
  exit 1
fi

# 1. Special case: 'stable'
if [[ "$TYPE" == "stable" ]]; then
  TARGET_TAG="stable"
  if git rev-parse "stable" >/dev/null 2>&1; then
    echo "Updating 'stable' tag to current commit..."
    git tag -d stable >/dev/null
    git push origin :refs/tags/stable >/dev/null 2>&1 || true
  fi
  git tag -a "stable" -m "Release stable"
  echo "✅ Tag 'stable' assigned successfully."
  exit 0
fi

# 2. Retrieve latest SemVer tag in repository (defaults to v0.0.0 if none exists)
LATEST_TAG=$(git describe --tags --match "v[0-9]*.[0-9]*.[0-9]*" --abbrev=0 2>/dev/null || echo "v0.0.0")

# Strip leading 'v'
CLEAN_VERSION="${LATEST_TAG#v}"
IFS='.' read -r MAJOR MINOR PATCH <<< "$CLEAN_VERSION"

# 3. Compute next version based strictly on the semantic level
case "$TYPE" in
  patch)
    PATCH=$((PATCH + 1))
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
  *)
    echo "Error: Invalid parameter '$TYPE'."
    echo "Valid semantic options: 'patch', 'minor', 'major', or 'stable'."
    exit 1
    ;;
esac

TARGET_TAG="v${MAJOR}.${MINOR}.${PATCH}"
echo "Latest tag detected: $LATEST_TAG"
echo "Calculated next version ($TYPE): $TARGET_TAG"

# Check if target tag already exists
if git rev-parse "$TARGET_TAG" >/dev/null 2>&1; then
  echo "Error: Tag '$TARGET_TAG' already exists in repository."
  exit 1
fi

# Create annotated tag
git tag -a "$TARGET_TAG" -m "Release $TARGET_TAG"
echo "✅ Tag '$TARGET_TAG' created successfully."