#!/usr/bin/env bash
# Удаление klippa. По умолчанию данные пользователя (история, конфиг, ключ)
# сохраняются. Флаг --purge удаляет и их.
set -euo pipefail

UUID="klippa@local"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

EXT_DST="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID"
DAEMON_DST="${XDG_DATA_HOME:-$HOME/.local/share}/klippa"
UNIT_DST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/klippad.service"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/klippa"

echo "==> Выключение расширения"
gnome-extensions disable "$UUID" 2>/dev/null || true
rm -rf "$EXT_DST"

echo "==> Остановка демона"
systemctl --user disable --now klippad.service 2>/dev/null || true
rm -f "$UNIT_DST"
systemctl --user daemon-reload || true

echo "==> Удаление файлов демона"
rm -rf "$DAEMON_DST/klippad"

if [ "$PURGE" = "1" ]; then
  echo "==> --purge: удаляю историю, конфиг и предлагаю снять ключ из keyring"
  rm -rf "$DAEMON_DST"
  rm -rf "$CONFIG_DIR"
  echo "    Ключ шифрования остаётся в gnome-keyring; снять вручную:"
  echo "      secret-tool clear app klippa purpose history-encryption"
else
  echo "==> Данные сохранены ($DAEMON_DST, $CONFIG_DIR). Полное удаление: --purge"
fi

echo "==> Готово. На Wayland изменения расширения вступят в силу после перелогина."
