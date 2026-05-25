# klippa — менеджер буфера обмена для GNOME Shell / Wayland

Минималистичный менеджер буфера: ловит текст и изображения (включая скриншоты),
хранит последние N записей, по горячей клавише показывает меню **у курсора** с
навигацией только клавиатурой, по Enter вставляет выбранное в активное окно.
История хранится зашифрованно. Написан под личный setup (Ubuntu, GNOME 50,
Wayland), без оглядки на мультиплатформенность.

- [Почему так устроено: ограничения Wayland](#почему-гибрид)
- [Архитектура и поток данных](#архитектура)
- [Установка](#установка) · [Удаление](#удаление)
- [Конфигурация](#конфигурация)
- [Безопасность](#модель-безопасности)
- [Контракт D-Bus](#контракт-d-bus)
- [Раскладка кода](#раскладка-кода)
- [Тесты](#тесты) · [Диагностика](#диагностика) · [Обновление GNOME](#обновление-gnome)

---

## Почему гибрид

На GNOME Wayland внешний процесс **физически не может**:

1. **читать буфер в фоне** — нет протоколов `wlr-data-control`/`ext-data-control`,
   а стандартный `wl_data_device` отдаёт содержимое только окну *в фокусе*. Фоновый
   демон фокуса не имеет. Именно поэтому diodon/copyq теряют копирования из нативных
   Wayland-приложений;
2. **открыть окно у курсора** — нет `wlr-layer-shell`, компоновщик сам решает, где
   разместить окно внешнего приложения.

Обе операции доступны только коду **внутри** gnome-shell. Поэтому klippa — гибрид:

- **Расширение GNOME** (`extension/`, GJS) — тонкий слой View+Input: захват буфера,
  popup у курсора, навигация, грабинг хоткея, авто-вставка. Трогает только стабильный
  clipboard/UI API.
- **Демон** (`daemon/`, Python) — вся логика: история, дедупликация, конфиг,
  шифрование, политика безопасности. Не зависит от жизненного цикла shell.

Связь — через session D-Bus (`org.klippa.Daemon`), доступный лишь внутри сессии.

## Архитектура

```
                      D-Bus session bus · org.klippa.Daemon
 ┌────────────────────────┐   Capture(kind,data,app,ts,secret)  ┌──────────────────────┐
 │ extension klippa@local │ ──────────────────────────────────▶ │   daemon  klippad     │
 │ (GJS, внутри shell)    │   GetHistory / GetThumbnail          │  (Python, systemd)    │
 │                        │ ◀────── GetContent ───────────────── │                       │
 │ • clipboard.js захват  │   Promote / Delete / Clear           │ • store  ring+MRU     │
 │ • popup.js  меню/навиг.│ ──────────────────────────────────▶ │ • db     SQLite+AES   │
 │ • extension.js хоткей  │ ◀────── HistoryChanged (signal) ──── │ • crypto keyring-ключ │
 └────────────────────────┘                                     │ • config TOML+watch   │
                                                                 │ • thumbs GdkPixbuf    │
                                                                 └──────────────────────┘
```

**Поток «скопировал → вставил»:**

1. Пользователь копирует. `Meta.Selection` шлёт `owner-changed` → `clipboard.js`
   читает `St.Clipboard`, определяет text/image по MIME, отбрасывает помеченное
   менеджером паролей, вызывает `Capture(...)`.
2. Демон дедуплицирует (повтор поднимает запись в топ), вытесняет старейшее сверх
   `max_entries`, шифрует и пишет в SQLite, эмитит `HistoryChanged`.
3. Пользователь жмёт хоткей → `popup.js` открывает меню у курсора, тянет
   `GetHistory`, рисует превью (для картинок — `GetThumbnail`).
4. Стрелки/набор текста — выбор/фильтр. Enter → `Promote(id)` + `GetContent(id)` →
   запись в буфер → закрытие popup → синтез `Ctrl+V` в прежнее окно (если включено).

## Установка

Требуется GNOME Shell на Wayland. Системные зависимости (Ubuntu/Debian):

```bash
sudo apt install python3-gi gir1.2-glib-2.0 gir1.2-gdkpixbuf-2.0 \
                 gir1.2-secret-1 python3-cryptography
```

Затем:

```bash
./packaging/install.sh
```

Скрипт проверит зависимости, поставит демон в `~/.local/share/klippa/`, расширение
в `~/.local/share/gnome-shell/extensions/klippa@local/`, скомпилирует схемы,
включит systemd-юнит `klippad.service` и расширение.

**На Wayland нужно перелогиниться** (shell не перезагружается на лету). После входа:

```bash
gnome-extensions info klippa@local      # State: ACTIVE
systemctl --user status klippad         # active (running)
```

По умолчанию хоткей — `<Super>v`.

## Удаление

Из корня репозитория:

```bash
./uninstall.sh           # удалить компоненты, данные сохранить
./uninstall.sh --purge   # + удалить историю, конфиг и ключ из gnome-keyring
```

(`./uninstall.sh` — тонкая обёртка над `packaging/uninstall.sh`; можно звать и его
напрямую.) Скрипт отключает расширение, останавливает и убирает systemd-юнит,
удаляет файлы демона и расширения. Без `--purge` история/конфиг/ключ сохраняются —
повторная установка подхватит прежнюю историю.

## Конфигурация

Файл `~/.config/klippa/config.toml` создаётся при первом старте. Демон следит за ним
и применяет изменения на лету; хоткей/лимит/авто-вставка зеркалятся в настройки
расширения автоматически.

| Ключ | Тип | Дефолт | Назначение |
|---|---|---|---|
| `hotkey` | строка | `"<Super>v"` | комбинация вызова меню (GTK-акселератор) |
| `max_entries` | целое | `50` | сколько записей хранить; сверх — вытеснение старейшего |
| `capture_images` | bool | `true` | ловить изображения и скриншоты |
| `max_image_mb` | целое | `10` | картинки крупнее — игнорировать |
| `auto_paste` | bool | `true` | вставлять выбранное `Ctrl+V` автоматически |
| `skip_secrets` | bool | `true` | пропускать помеченное менеджерами паролей |
| `expire_days` | целое | `0` | удалять записи старше N дней (0 — выключено) |

## Модель безопасности

- **Без сети.** Демон слушает только session D-Bus; ни сокетов наружу, ни телеметрии.
- **Шифрование на диске.** Каждое значение — AES-256-GCM (уникальный nonce, тег
  целостности). Ключ генерируется один раз и хранится в **gnome-keyring** (libsecret),
  не рядом с БД. Файл БД `~/.local/share/klippa/history.db` — права `0600`.
- **Превью не утекает.** В БД не хранится превью (производно от содержимого) —
  пересчитывается при загрузке. Миниатюры картинок живут только в памяти демона и
  отдаются по D-Bus; на диск не пишутся.
- **Фильтр секретов.** Записи с MIME-подсказкой менеджеров паролей не сохраняются —
  проверка и в расширении (не отправлять), и в демоне (не принимать).
- **Лимиты.** Потолок на размер текста и картинки; вытеснение по `max_entries`.
- **Очистка.** `Clear()` (через D-Bus) стирает память и БД; опциональное
  авто-истечение по `expire_days`.
- **Минимум привилегий.** Расширение не хранит данных; демон — `NoNewPrivileges`.

## Контракт D-Bus

Полностью — в [`dbus-interface.md`](dbus-interface.md) и [`dbus-interface.xml`](dbus-interface.xml).
Кратко (`org.klippa.Daemon1` на `/org/klippa/Daemon`):

`Capture(kind,data,app,ts,sensitive)` · `GetHistory(limit)→json` ·
`GetThumbnail(id)→png` · `GetContent(id)→(kind,data)` · `Promote(id)` ·
`Delete(id)` · `Clear()` · сигнал `HistoryChanged`.

## Раскладка кода

```
daemon/klippad/
  store.py     модель Entry + кольцевой буфер, dedup/MRU, вытеснение   (чистый Python)
  config.py    парсинг TOML + hot-reload (Gio.FileMonitor)
  crypto.py    AES-256-GCM + ключ из gnome-keyring
  db.py        зашифрованная SQLite, sync со Store, восстановление MRU
  thumbs.py    миниатюры через GdkPixbuf (в памяти)
  service.py   D-Bus сервис org.klippa.Daemon, оркестрация
  __main__.py  сборка компонентов + главный цикл GLib
daemon/tests/  pytest: store / config / crypto / db / thumbs

extension/klippa@local/
  metadata.json  манифест (uuid, shell-version, схема)
  schemas/       GSettings-схема (hotkey, popup-limit, auto-paste)
  dbus.js        клиент к демону (Gio.DBusProxy)
  clipboard.js   захват буфера (Meta.Selection + St.Clipboard)
  popup.js       меню у курсора: навигация, фильтр, миниатюры, авто-вставка
  extension.js   хоткей + жизненный цикл
  stylesheet.css стили popup

packaging/   klippad.service, install.sh, uninstall.sh, gnome-upgrade.sh
docs/        этот файл, контракт D-Bus, GNOME-UPGRADE.md, smoke-checklist.md
```

Граница «gi ↔ ядро» проведена намеренно: `store/config/crypto/db` не зависят от gi
и покрыты unit-тестами; gi/UI-слой (`service/thumbs` и всё расширение) проверяется
[smoke-чеклистом](smoke-checklist.md).

## Тесты

```bash
cd daemon && PYTHONPATH=. python3 -m pytest -q
```

Покрыты ядро хранилища (ring/dedup/MRU/eviction), парсинг и валидация конфига,
round-trip шифрования и детект порчи, персистентность (порядок, шифрование на диске,
права, очистка). Тест миниатюр пропускается при отсутствии gi. Функциональный цикл
(захват→попап→вставка) — ручной [smoke-чеклист](smoke-checklist.md).

## Диагностика

```bash
journalctl --user -u klippad -f                  # логи демона
journalctl /usr/bin/gnome-shell -b 0 | grep -i klippa   # ошибки расширения
gnome-extensions info klippa@local               # состояние расширения
busctl --user introspect org.klippa.Daemon /org/klippa/Daemon  # интерфейс жив
```

Типичное:

- **Меню не открывается** — проверьте, что расширение `ACTIVE` и вы перелогинились
  после установки; проверьте конфликт хоткея с системным.
- **Копии не попадают в историю** — жив ли демон (`systemctl --user status klippad`),
  доступен ли по D-Bus (`busctl` выше). Помните: содержимое менеджеров паролей
  пропускается намеренно.
- **Авто-вставка не срабатывает** — некоторым окнам нужен фокус; при сбоях задайте
  `auto_paste = false` и вставляйте `Ctrl+V` сами.
- **Ключ шифрования** — хранится в gnome-keyring (`secret-tool search app klippa`).
  При удалении ключа старая БД станет нечитаемой (это by design).

## Обновление GNOME

Мажорный апдейт GNOME может сломать расширение. Процедура и список затрагиваемых
Shell-API — в [`GNOME-UPGRADE.md`](GNOME-UPGRADE.md). Коротко: `./packaging/gnome-upgrade.sh`,
перелогин, smoke-чеклист.
