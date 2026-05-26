// Страница настроек klippa (Adw/Gtk4). Запускается отдельным процессом
// (gnome-extensions prefs), поэтому НЕ делит состояние с расширением.
//
// Источник истины — config.toml демона. Поэтому prefs не пишет в GSettings, а
// читает/пишет конфиг по D-Bus (GetConfig/SetConfig); демон сохраняет файл и
// применяет на лету, а уже он зеркалит хоткей/лимит/авто-вставку в GSettings,
// откуда расширение их подхватывает. Так все ключи (в т.ч. демон-only:
// capture_images, max_image_mb, skip_secrets, expire_days) попадают куда нужно.

import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const BUS_NAME = 'org.klippa.Daemon';
const OBJECT_PATH = '/org/klippa/Daemon';

// Подмножество контракта IPC-001, нужное только настройкам.
const IFACE_XML = `
<node>
  <interface name="org.klippa.Daemon1">
    <method name="GetConfig"><arg name="json" type="s" direction="out"/></method>
    <method name="SetConfig"><arg name="json" type="s" direction="in"/></method>
  </interface>
</node>`;

const KlippaConfigProxy = Gio.DBusProxy.makeProxyWrapper(IFACE_XML);

// Дефолты — зеркало Config в daemon/klippad/config.py. Используются как база, на
// которую накладывается ответ GetConfig (forward-compat при добавлении ключей).
const DEFAULTS = {
    hotkey: '<Super>v',
    max_entries: 50,
    capture_images: true,
    max_image_mb: 10,
    auto_paste: true,
    skip_secrets: true,
    expire_days: 0,
};

// Голые модификаторы, которые сами по себе не образуют комбинацию.
const MODIFIER_KEYVALS = new Set([
    Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
    Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
    Gdk.KEY_Super_L, Gdk.KEY_Super_R,
    Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
    Gdk.KEY_Hyper_L, Gdk.KEY_Hyper_R,
    Gdk.KEY_ISO_Level3_Shift, Gdk.KEY_Caps_Lock, Gdk.KEY_Num_Lock,
]);

function isFunctionKey(keyval) {
    return keyval >= Gdk.KEY_F1 && keyval <= Gdk.KEY_F12;
}

export default class KlippaPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const page = new Adw.PreferencesPage();
        window.add(page);

        let proxy = null;
        let cfg = {...DEFAULTS};
        try {
            proxy = KlippaConfigProxy(Gio.DBus.session, BUS_NAME, OBJECT_PATH);
            const [json] = proxy.GetConfigSync();
            cfg = {...DEFAULTS, ...JSON.parse(json)};
        } catch (e) {
            console.error(`klippa prefs: демон недоступен: ${e}`);
            page.add(this._unavailableGroup());
            return;
        }

        // Защита от петли: установка значений в виджеты тоже шлёт notify::*.
        let loading = true;
        const push = () => {
            if (loading || !proxy)
                return;
            proxy.SetConfigRemote(JSON.stringify(cfg), (_r, err) => {
                if (err)
                    console.error(`klippa prefs: SetConfig: ${err}`);
            });
        };

        // --- Поведение ------------------------------------------------------
        const behaviour = new Adw.PreferencesGroup({title: 'Поведение'});
        behaviour.add(this._shortcutRow(cfg, push));

        const autoPaste = new Adw.SwitchRow({
            title: 'Авто-вставка',
            subtitle: 'Вставлять выбранное Ctrl+V в прежнее окно (иначе — только в буфер)',
            active: cfg.auto_paste,
        });
        autoPaste.connect('notify::active', () => {
            cfg.auto_paste = autoPaste.get_active();
            push();
        });
        behaviour.add(autoPaste);
        page.add(behaviour);

        // --- История --------------------------------------------------------
        const history = new Adw.PreferencesGroup({title: 'История'});
        const maxEntries = this._spinRow(
            'Размер истории', 'Сколько последних записей хранить',
            cfg.max_entries, 1, 500,
            v => { cfg.max_entries = v; push(); });
        history.add(maxEntries);

        const expireDays = this._spinRow(
            'Срок хранения, дней', 'Удалять записи старше N дней (0 — не удалять)',
            cfg.expire_days, 0, 3650,
            v => { cfg.expire_days = v; push(); });
        history.add(expireDays);
        page.add(history);

        // --- Захват ---------------------------------------------------------
        const capture = new Adw.PreferencesGroup({title: 'Захват'});
        const captureImages = new Adw.SwitchRow({
            title: 'Захватывать изображения',
            subtitle: 'Картинки из буфера и скриншоты',
            active: cfg.capture_images,
        });
        captureImages.connect('notify::active', () => {
            cfg.capture_images = captureImages.get_active();
            push();
        });
        capture.add(captureImages);

        const maxImage = this._spinRow(
            'Макс. размер картинки, МБ', 'Изображения крупнее — игнорировать',
            cfg.max_image_mb, 1, 100,
            v => { cfg.max_image_mb = v; push(); });
        capture.add(maxImage);

        const skipSecrets = new Adw.SwitchRow({
            title: 'Пропускать секреты',
            subtitle: 'Не хранить помеченное менеджерами паролей',
            active: cfg.skip_secrets,
        });
        skipSecrets.connect('notify::active', () => {
            cfg.skip_secrets = skipSecrets.get_active();
            push();
        });
        capture.add(skipSecrets);
        page.add(capture);

        loading = false;
    }

    // Строка-спиннер для целочисленного параметра.
    _spinRow(title, subtitle, value, lower, upper, onChange) {
        const row = new Adw.SpinRow({
            title,
            subtitle,
            adjustment: new Gtk.Adjustment({
                lower, upper, value, step_increment: 1, page_increment: 10,
            }),
        });
        row.connect('notify::value', () => onChange(row.get_value()));
        return row;
    }

    // Строка захвата горячей клавиши: клик → ждём комбинацию, пишем cfg.hotkey.
    _shortcutRow(cfg, push) {
        const row = new Adw.ActionRow({
            title: 'Горячая клавиша',
            subtitle: 'Комбинация вызова меню (нужен модификатор или F-клавиша)',
        });
        const button = new Gtk.Button({valign: Gtk.Align.CENTER});
        row.add_suffix(button);
        row.activatable_widget = button;

        const showAccel = () => {
            const [ok, keyval, mods] = Gtk.accelerator_parse(cfg.hotkey);
            button.label = ok && keyval
                ? Gtk.accelerator_get_label(keyval, mods)
                : '(не задано)';
            button.remove_css_class('suggested-action');
        };
        showAccel();

        let controller = null;
        const stopCapture = () => {
            if (controller) {
                button.get_root()?.remove_controller(controller);
                controller = null;
            }
            showAccel();
        };

        button.connect('clicked', () => {
            if (controller)
                return; // уже ловим
            button.label = 'Нажмите комбинацию… (Esc — отмена)';
            button.add_css_class('suggested-action');

            controller = new Gtk.EventControllerKey();
            controller.connect('key-pressed', (_c, keyval, _keycode, state) => {
                if (keyval === Gdk.KEY_Escape) {
                    stopCapture();
                    return Gdk.EVENT_STOP;
                }
                if (MODIFIER_KEYVALS.has(keyval))
                    return Gdk.EVENT_STOP; // ждём не-модификатор
                const mods = state & Gtk.accelerator_get_default_mod_mask();
                if (mods === 0 && !isFunctionKey(keyval))
                    return Gdk.EVENT_STOP; // голую клавишу как глобальный хоткей не берём
                const accel = Gtk.accelerator_name(keyval, mods);
                if (accel) {
                    cfg.hotkey = accel;
                    push();
                }
                stopCapture();
                return Gdk.EVENT_STOP;
            });
            button.get_root().add_controller(controller);
        });

        return row;
    }

    // Группа-заглушка, когда демон не запущен.
    _unavailableGroup() {
        const group = new Adw.PreferencesGroup();
        const row = new Adw.ActionRow({
            title: 'Демон klippad не отвечает',
            subtitle: 'Запустите: systemctl --user start klippad — затем откройте настройки заново. '
                + 'Либо отредактируйте ~/.config/klippa/config.toml вручную.',
        });
        row.add_prefix(new Gtk.Image({icon_name: 'dialog-warning-symbolic'}));
        group.add(row);
        return group;
    }
}
