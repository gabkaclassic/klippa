#!/usr/bin/env bash
# Простое удаление klippa из корня репозитория.
#   ./uninstall.sh           — удалить компоненты, данные сохранить
#   ./uninstall.sh --purge    — + удалить историю, конфиг и ключ из keyring
# Тонкая обёртка над packaging/uninstall.sh (канонический скрипт).
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/packaging/uninstall.sh" "$@"
