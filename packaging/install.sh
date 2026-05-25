#!/usr/bin/env bash
# Установка klippa под текущего пользователя (GNOME Shell / Wayland).
# Идемпотентно: повторный запуск обновляет уже установленное.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UUID="klippa@local"

EXT_SRC="$REPO_ROOT/extension/$UUID"
EXT_DST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"
DAEMON_SRC="$REPO_ROOT/daemon/klippad"
DAEMON_DST="${XDG_DATA_HOME:-$HOME/.local/share}/klippa/klippad"
UNIT_SRC="$REPO_ROOT/packaging/klippad.service"
UNIT_DST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/klippad.service"

# Демон работает под интерпретатором из ExecStart юнита (единый источник истины),
# поэтому и зависимости проверяем ИМ ЖЕ, а не тем python3, что сейчас в PATH.
# Иначе активный venv (без --system-site-packages) не видит системный python3-gi
# и проверка ложно сообщает о нехватке уже установленных пакетов.
DAEMON_PYTHON="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "$UNIT_SRC")"
DAEMON_PYTHON="${DAEMON_PYTHON:-/usr/bin/python3}"

echo "==> Проверка зависимостей (интерпретатор демона: $DAEMON_PYTHON)"
if [ -n "${VIRTUAL_ENV:-}" ]; then
  echo "   (активен venv $VIRTUAL_ENV — он намеренно игнорируется: демон"
  echo "    запускается системным python из юнита, а не из venv)"
fi
if [ ! -x "$DAEMON_PYTHON" ]; then
  echo "!! Интерпретатор $DAEMON_PYTHON не найден. Поправьте ExecStart в $UNIT_SRC."
  exit 1
fi

missing=()
"$DAEMON_PYTHON" -c "import gi" 2>/dev/null || missing+=("python3-gi")
"$DAEMON_PYTHON" -c "import cryptography" 2>/dev/null || missing+=("python3-cryptography")
for ns in "Gio:2.0" "GLib:2.0" "GdkPixbuf:2.0" "Secret:1"; do
  "$DAEMON_PYTHON" - "$ns" <<'PY' 2>/dev/null || missing+=("typelib:${ns}")
import sys, gi
n, v = sys.argv[1].split(":")
gi.require_version(n, v)
PY
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "!! В $DAEMON_PYTHON не хватает: ${missing[*]}"
  echo "   Ubuntu: sudo apt install python3-gi gir1.2-glib-2.0 gir1.2-gdkpixbuf-2.0 gir1.2-secret-1 python3-cryptography"
  echo "   Если пакеты уже стоят системно, а ошибка осталась — значит проверяется"
  echo "   не системный python. Убедитесь, что $DAEMON_PYTHON это /usr/bin/python3."
  exit 1
fi

echo "==> Установка демона в $DAEMON_DST"
rm -rf "$DAEMON_DST"
mkdir -p "$(dirname "$DAEMON_DST")"
cp -r "$DAEMON_SRC" "$DAEMON_DST"
find "$DAEMON_DST" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "==> Установка расширения в $EXT_DST"
rm -rf "$EXT_DST"
mkdir -p "$EXT_DST"
cp -r "$EXT_SRC/." "$EXT_DST/"
rm -f "$EXT_DST/schemas/gschemas.compiled"
glib-compile-schemas "$EXT_DST/schemas"

echo "==> systemd --user юнит"
mkdir -p "$(dirname "$UNIT_DST")"
cp "$UNIT_SRC" "$UNIT_DST"
systemctl --user daemon-reload
systemctl --user enable --now klippad.service
echo "    демон: $(systemctl --user is-active klippad.service)"

echo "==> Включение расширения"
gnome-extensions enable "$UUID" || \
  echo "    (расширение включится после перезахода — это нормально на Wayland)"

cat <<'EOF'

==> Готово.
    На Wayland gnome-shell нельзя перезагрузить без перелогина:
    выйдите из сессии и войдите снова, затем проверьте:
      gnome-extensions info klippa@local
      journalctl --user -u klippad -f
    Конфиг: ~/.config/klippa/config.toml (создаётся при первом старте).
EOF
