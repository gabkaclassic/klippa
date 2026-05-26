#!/usr/bin/env bash
# Поднять целочисленную version в metadata.json расширения (поле version у
# GNOME-расширений — монотонное целое, не semver).
#   ./packaging/bump-version.sh           # +1 к текущей
#   ./packaging/bump-version.sh 7         # выставить ровно 7
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
META="$REPO_ROOT/extension/klippa@local/metadata.json"

cur="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$META")"

if [ $# -ge 1 ]; then
  next="$1"
  case "$next" in (*[!0-9]*|'') echo "!! версия должна быть целым числом" >&2; exit 1;; esac
else
  next=$((cur + 1))
fi

python3 - "$META" "$next" <<'PY'
import json, sys
path, nxt = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as f:
    meta = json.load(f)
meta["version"] = nxt
with open(path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY

echo "version: $cur → $next  ($META)"
echo "Собрать zip:  ./packaging/pack.sh"
