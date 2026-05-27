#!/bin/sh
# postinst: запускается от root без пользовательской сессии.
# Делает только то, что доступно root: компилирует схему GSettings расширения.
# Активация — per-user и полностью через klippa-enable (расширение в dconf +
# старт сервиса в сессии), поэтому глобально сервис НЕ включаем.
set -e

SCHEMA_DIR=/usr/share/gnome-shell/extensions/klippa@local/schemas
if [ -d "$SCHEMA_DIR" ] && command -v glib-compile-schemas >/dev/null 2>&1; then
  glib-compile-schemas "$SCHEMA_DIR" || true
fi

# Подчистить возможный глобальный enable от старых версий пакета (<=0.1.2 ставили
# симлинки в /etc/systemd/user), иначе он перекрывал бы per-user klippa-disable.
if command -v systemctl >/dev/null 2>&1; then
  systemctl --global disable klippad.service >/dev/null 2>&1 || true
fi

cat <<'EOF'
klippa установлена системно. Каждому пользователю один раз выполнить:
    klippa-enable
затем перелогиниться (Wayland не перезагружает gnome-shell на лету).
Управление: klippa-config (настройки), klippa-disable (отключить).
EOF

exit 0
