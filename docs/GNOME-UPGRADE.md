# Обновление klippa под новую мажорную версию GNOME

Расширения GNOME Shell привязаны к версии shell, а Shell-API между мажорными
релизами меняется. Это главный риск сопровождения (R-1). Процедура —
инструментальная, не «по памяти».

## Быстрый путь

После обновления GNOME выполните:

```bash
./packaging/gnome-upgrade.sh
```

Скрипт допишет текущую мажорную версию в `metadata.json`, перекомпилирует схемы,
переустановит расширение и перезапустит демон. Затем **перелогиньтесь** (на
Wayland shell не перезагружается на лету) и пройдите чеклист ниже.

## Чеклист после перелогина

```bash
gnome-extensions info klippa@local           # State: ACTIVE, ошибок нет
journalctl /usr/bin/gnome-shell -b 0 | grep -i klippa   # пусто = хорошо
journalctl --user -u klippad -b 0            # демон поднялся
```

Затем — функциональный smoke: `docs/smoke-checklist.md`.

## Если расширение сломалось

Демон (Python, D-Bus) от версии GNOME не зависит — ломается обычно расширение.
Проверьте в changelog GNOME Shell / Mutter изменения по этим точкам API, которые
использует klippa:

| Где в коде | Используемый API | Что проверить |
|---|---|---|
| `clipboard.js` | `global.display.get_selection()`, сигнал `owner-changed`, `Meta.SelectionType.SELECTION_CLIPBOARD` | переименование/сигнатура сигнала, enum типов выделения |
| `clipboard.js`, `popup.js` | `St.Clipboard`: `get_mimetypes`, `get_text`, `get_content`, `set_text`, `set_content` | сигнатуры коллбеков, `St.ClipboardType` |
| `popup.js` | `Main.pushModal`/`Main.popModal`, объект grab | форма опций (`actionMode`), возвращаемое значение |
| `popup.js` | `St.ScrollView` (`set_child`/`vadjustment`), `St.ImageContent`, `Cogl.PixelFormat` | смена API контейнера/контента |
| `popup.js` | `Clutter` virtual device: `get_default_seat().create_virtual_device`, `notify_keyval`, `Clutter.KeyState` | сигнатуры синтеза ввода |
| `extension.js` | `Main.wm.addKeybinding`/`removeKeybinding`, `Shell.ActionMode`, `Meta.KeyBindingFlags` | флаги, режимы |
| `extension.js` | базовый класс `Extension` из `resource:///org/gnome/shell/extensions/extension.js`, ESM-импорты `gi://`, `getSettings()` | формат загрузки модулей расширения |
| `prefs.js` | `ExtensionPreferences` из `resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js`, `Adw.PreferencesPage/Group`, `Adw.SpinRow`, `Adw.SwitchRow` | libadwaita-мажор (Gtk4/Adw1), наличие строк-виджетов |
| `prefs.js` | `Gtk.EventControllerKey` (`key-pressed`), `Gtk.accelerator_name/parse/get_label`, `Gtk.accelerator_get_default_mod_mask`, `Gdk.KEY_*` | API захвата комбинации клавиш |
| весь модуль | формат `metadata.json` (`shell-version`, `settings-schema`) | требования к полям |

Логи ошибок расширения: `journalctl /usr/bin/gnome-shell -b 0`.
Интерактивная отладка: `Alt+F2` → `lg` (Looking Glass) или
`journalctl /usr/bin/gnome-shell -f` при включении расширения.

## Откат

1. Уберите новую версию из `shell-version` в `metadata.json` (или
   `git checkout extension/klippa@local/metadata.json`).
2. `gnome-extensions disable klippa@local` — отключить, пока чините.
3. Демон при этом продолжает копить историю (доступна после починки
   расширения), данные не теряются.
