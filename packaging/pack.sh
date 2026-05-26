#!/usr/bin/env bash
# Собрать устанавливаемый zip расширения через gnome-extensions pack.
# Результат: dist/klippa@local.shell-extension.zip
# Установка из него:  gnome-extensions install --force dist/klippa@local.shell-extension.zip
# (затем перелогин на Wayland — демон ставится отдельно через install.sh).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UUID="klippa@local"
EXT_SRC="$REPO_ROOT/extension/$UUID"
DIST="$REPO_ROOT/dist"

if ! command -v gnome-extensions >/dev/null 2>&1; then
  echo "!! нет gnome-extensions (пакет gnome-shell). Установить нечем — прерываю." >&2
  exit 1
fi

mkdir -p "$DIST"

# gnome-extensions pack сам включает metadata.json, extension.js, prefs.js,
# stylesheet.css и schemas/. Остальные JS-модули добавляем явно --extra-source.
EXTRA=(dbus.js clipboard.js popup.js)
extra_args=()
for f in "${EXTRA[@]}"; do
  [ -f "$EXT_SRC/$f" ] && extra_args+=(--extra-source="$f")
done

echo "==> Сборка zip из $EXT_SRC"
gnome-extensions pack "$EXT_SRC" \
  --force \
  --out-dir="$DIST" \
  "${extra_args[@]}"

ZIP="$DIST/$UUID.shell-extension.zip"
echo "==> Готово: $ZIP"
echo "    содержимое:"
unzip -l "$ZIP" | sed 's/^/      /'
echo
echo "    Установка:  gnome-extensions install --force \"$ZIP\""
echo "    (демон — отдельно: ./packaging/install.sh; на Wayland нужен перелогин)"
