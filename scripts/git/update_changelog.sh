#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-}"
SUMMARY="${2:-"Routine updates and stability fixes."}"

if [[ -z "$VERSION" ]]; then
  echo "Error: Version parameter is required (e.g., v0.1.0 or 0.1.0)."
  exit 1
fi

# Eliminar prefijo 'v' si viene incluido para el formato del Header
CLEAN_VERSION="${VERSION#v}"
CURRENT_DATE=$(date +%Y-%m-%d)
CHANGELOG_FILE="CHANGELOG.md"

if [[ ! -f "$CHANGELOG_FILE" ]]; then
  echo "# Changelog" > "$CHANGELOG_FILE"
  echo "" >> "$CHANGELOG_FILE"
fi

# Preparar el nuevo bloque de versión
NEW_ENTRY=$(cat <<EOF
## [$CLEAN_VERSION] - $CURRENT_DATE
### Changed
- **Release $VERSION**: $SUMMARY

EOF
)

# Insertar la nueva versión justo debajo de '# Changelog'
python3 -c "
import sys

changelog_path = '$CHANGELOG_FILE'
new_entry = '''$NEW_ENTRY'''

with open(changelog_path, 'r') as f:
    content = f.read()

if '# Changelog' in content:
    parts = content.split('# Changelog', 1)
    updated = '# Changelog\n\n' + new_entry + parts[1].lstrip()
else:
    updated = '# Changelog\n\n' + new_entry + content

with open(changelog_path, 'w') as f:
    f.write(updated)
"

# AUTOMATIZAR EL COMMIT DENTRO DEL SCRIPT
git add "$CHANGELOG_FILE"
git commit -m "docs(changelog): update release notes for $VERSION"

echo "✅ $CHANGELOG_FILE updated and committed successfully for version $VERSION ($CURRENT_DATE)."