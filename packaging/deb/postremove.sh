#!/bin/sh
# postrm: запускается от root после удаления файлов пакета.
# Подчищаем артефакты, которые dpkg не отслеживает: gschemas.compiled создаётся
# нами в postinst, поэтому пустой каталог схемы без этого не удалится.
set -e

SCHEMA_DIR=/usr/share/gnome-shell/extensions/klippa@local/schemas
rm -f "$SCHEMA_DIR/gschemas.compiled" 2>/dev/null || true
rmdir "$SCHEMA_DIR" 2>/dev/null || true
rmdir /usr/share/gnome-shell/extensions/klippa@local 2>/dev/null || true
rmdir /usr/share/klippa 2>/dev/null || true

# Per-user состояние (~/.config/klippa, ~/.local/share/klippa, dconf-флаг
# расширения) намеренно не трогаем — это данные пользователя.
exit 0
