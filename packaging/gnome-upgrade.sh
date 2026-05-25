#!/usr/bin/env bash
# Адаптация klippa к новой мажорной версии GNOME Shell.
# Запускать ПОСЛЕ обновления GNOME. Идемпотентно.
#
# Что делает:
#   1) определяет текущую мажорную версию Shell;
#   2) дописывает её в metadata.json -> shell-version (если ещё нет);
#   3) перекомпилирует схемы и переустанавливает расширение;
#   4) перезапускает демон;
#   5) печатает чеклист ручной проверки (см. docs/GNOME-UPGRADE.md).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
META="$REPO_ROOT/extension/klippa@local/metadata.json"

echo "==> Определяю версию GNOME Shell"
RAW="$(gnome-shell --version 2>/dev/null || echo '')"
MAJOR="$(printf '%s' "$RAW" | grep -oE '[0-9]+' | head -n1 || true)"
if [ -z "$MAJOR" ]; then
  echo "!! Не удалось определить версию (вывод: '$RAW'). Прерываю."
  exit 1
fi
echo "    GNOME Shell major = $MAJOR"

echo "==> Обновляю shell-version в metadata.json (идемпотентно)"
python3 - "$META" "$MAJOR" <<'PY'
import json, sys
path, major = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
versions = data.get("shell-version", [])
if major in versions:
    print(f"    {major} уже в списке: {versions}")
else:
    versions.append(major)
    # держим отсортированным по числовому значению
    versions = sorted(set(versions), key=lambda v: int(v))
    data["shell-version"] = versions
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(path, "a").write("\n")
    print(f"    добавлено -> {versions}")
PY

echo "==> Переустановка расширения и перезапуск демона"
"$REPO_ROOT/packaging/install.sh"

cat <<EOF

==> Версия добавлена и компоненты переустановлены.
    ОБЯЗАТЕЛЬНО перелогиньтесь (Wayland не перезагружает shell на лету).

    После входа пройдите чеклист совместимости (docs/GNOME-UPGRADE.md):
      • расширение включилось:    gnome-extensions info klippa@local
      • ошибок shell нет:         journalctl /usr/bin/gnome-shell -b 0 | grep -i klippa
      • демон жив:                journalctl --user -u klippad -b 0
      • захват/попап/вставка работают (docs/smoke-checklist.md)

    Если расширение падает после апдейта — проверьте Shell-API из
    docs/GNOME-UPGRADE.md (Meta.Selection, St.Clipboard, Main.pushModal,
    addKeybinding, Clutter virtual device). Откат: уберите $MAJOR из
    shell-version и сообщите, что именно сломалось.
EOF
