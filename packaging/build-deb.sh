#!/usr/bin/env bash
# Собрать deb-пакет klippa через nfpm.
# Результат: dist/klippa_<version>_all.deb
# Установка:  sudo apt install ./dist/klippa_<version>_all.deb
#             (apt подтянет зависимости; затем каждый юзер — klippa-enable).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$REPO_ROOT/dist"
CONFIG="$REPO_ROOT/packaging/nfpm.yaml"

# nfpm: из $NFPM (например, скачанный бинарь) или из PATH.
NFPM="${NFPM:-nfpm}"
if ! command -v "$NFPM" >/dev/null 2>&1 && [ ! -x "$NFPM" ]; then
  echo "!! nfpm не найден. Установите его или задайте путь через NFPM=..." >&2
  echo "   Go:  go install github.com/goreleaser/nfpm/v2/cmd/nfpm@latest" >&2
  echo "   bin: https://github.com/goreleaser/nfpm/releases" >&2
  exit 1
fi

# Версия пакета — единый источник истины: __version__ демона.
KLIPPA_VERSION="$(
  sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' "$REPO_ROOT/daemon/klippad/__init__.py"
)"
if [ -z "$KLIPPA_VERSION" ]; then
  echo "!! не удалось прочитать __version__ из daemon/klippad/__init__.py" >&2
  exit 1
fi
export KLIPPA_VERSION

# Чистим то, что не должно попасть в пакет: байткод и скомпилированную схему
# (её пересоберёт postinst на целевой машине).
find "$REPO_ROOT/daemon/klippad" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f "$REPO_ROOT/extension/klippa@local/schemas/gschemas.compiled"

mkdir -p "$DIST"
echo "==> Сборка deb klippa $KLIPPA_VERSION"
# nfpm резолвит пути из nfpm.yaml относительно CWD — запускаем из корня репо.
( cd "$REPO_ROOT" && "$NFPM" package --config "$CONFIG" --packager deb --target "$DIST/" )

DEB="$(ls -t "$DIST"/klippa_*_all.deb 2>/dev/null | head -n1 || true)"
echo "==> Готово: ${DEB:-$DIST}"
if command -v dpkg-deb >/dev/null 2>&1 && [ -n "$DEB" ]; then
  echo "    содержимое:"
  dpkg-deb -c "$DEB" | sed 's/^/      /'
fi
echo
echo "    Установка:  sudo apt install \"$DEB\""
echo "    Затем каждому пользователю один раз:  klippa-enable  (и перелогин на Wayland)"
