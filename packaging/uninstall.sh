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
  echo "==> --purge: удаляю историю, конфиг и ключ из keyring"
  rm -rf "$DAEMON_DST"
  rm -rf "$CONFIG_DIR"
  if command -v secret-tool >/dev/null 2>&1; then
    secret-tool clear app klippa purpose history-encryption 2>/dev/null \
      && echo "    ключ шифрования снят из gnome-keyring" \
      || echo "    ключа в keyring не найдено (уже снят?)"
  else
    echo "    secret-tool не найден; снять ключ вручную позже:"
    echo "      secret-tool clear app klippa purpose history-encryption"
  fi
else
  echo "==> Данные сохранены ($DAEMON_DST, $CONFIG_DIR). Полное удаление: --purge"
fi

echo "==> Готово. На Wayland изменения расширения вступят в силу после перелогина."
