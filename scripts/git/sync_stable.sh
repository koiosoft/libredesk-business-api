#!/usr/bin/env bash
set -euo pipefail

echo "🔄 Syncing 'stable' with latest 'main' (without changing working branch)..."

HAS_REMOTE=false
if git remote get-url origin >/dev/null 2>&1; then
  HAS_REMOTE=true
fi

# 1. Traer la foto exacta de origin al segundo plano
if [[ "$HAS_REMOTE" == "true" ]]; then
  echo "📥 Fetching latest state from origin..."
  git fetch origin main:main stable:stable 2>/dev/null || git fetch origin --prune
fi

# 2. Asegurar que 'stable' exista localmente
if ! git rev-parse --verify stable >/dev/null 2>&1; then
  echo "ℹ️ Creating local 'stable' branch from 'main'..."
  git branch stable main
fi

# 3. Hacer MERGE de 'main' en 'stable' en SEGUNDO PLANO (sin checkout)
# Usamos un 'tree' temporal en Git para intentar la fusión sin alterar la carpeta de trabajo
echo "🔀 Merging 'main' into 'stable'..."
if ! git fetch . main:stable 2>/dev/null; then
  # Si el fast-forward no es suficiente, se usa un merge-tree defensivo
  MERGE_BASE=$(git merge-base stable main)
  TREE=$(git merge-tree "$MERGE_BASE" stable main | head -n 1)
  
  if [[ -z "$TREE" ]]; then
    echo "--------------------------------------------------------"
    echo "❌ Error: Merge conflict detected between 'main' and 'stable'."
    echo "Please merge 'main' into 'stable' manually to resolve conflicts."
    echo "--------------------------------------------------------"
    exit 1
  fi
  
  # Crear el commit de merge directamente en 'stable'
  NEW_COMMIT=$(git commit-tree "$TREE" -p stable -p main -m "Merge main into stable")
  git update-ref refs/heads/stable "$NEW_COMMIT"
fi

# 4. Si hay remoto, subir 'stable'
if [[ "$HAS_REMOTE" == "true" ]]; then
  echo "📤 Pushing updated 'stable' to origin..."
  if ! git push origin stable; then
    echo "❌ Error: Failed to push 'stable' to origin."
    exit 1
  fi
fi

echo "✅ 'stable' is now synchronized with 'main' and pushed to remote (your current branch was untouched!)."