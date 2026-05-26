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

mkdir -p "$DIST"
ZIP="$DIST/$UUID.shell-extension.zip"

if command -v gnome-extensions >/dev/null 2>&1; then
  # Штатный путь. gnome-extensions pack сам включает metadata.json, extension.js,
  # prefs.js, stylesheet.css и schemas/. Прочие JS-модули — явно --extra-source.
  EXTRA=(dbus.js clipboard.js popup.js)
  extra_args=()
  for f in "${EXTRA[@]}"; do
    [ -f "$EXT_SRC/$f" ] && extra_args+=(--extra-source="$f")
  done
  echo "==> Сборка через gnome-extensions pack"
  gnome-extensions pack "$EXT_SRC" --force --out-dir="$DIST" "${extra_args[@]}"
elif command -v zip >/dev/null 2>&1; then
  # Переносимый фолбэк (например, в CI без gnome-shell). Бандл — это zip файлов
  # расширения в корне архива; схему .gschema.xml компилирует сам
  # gnome-extensions install на целевой машине, поэтому компилировать здесь не нужно.
  echo "==> Сборка через zip (gnome-extensions недоступен)"
  rm -f "$ZIP"
  ( cd "$EXT_SRC" && zip -q -r "$ZIP" \
      metadata.json stylesheet.css ./*.js schemas/*.gschema.xml )
else
  echo "!! нет ни gnome-extensions, ни zip — собрать бандл нечем." >&2
  exit 1
fi
echo "==> Готово: $ZIP"
echo "    содержимое:"
unzip -l "$ZIP" | sed 's/^/      /'
echo
echo "    Установка:  gnome-extensions install --force \"$ZIP\""
echo "    (демон — отдельно: ./packaging/install.sh; на Wayland нужен перелогин)"
