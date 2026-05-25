// klippa — расширение GNOME Shell. Оркестрирует захват буфера, popup и хоткей;
// вся логика/хранение — в демоне klippad (D-Bus). Это слой View+Input.

import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {KlippaClient} from './dbus.js';
import {ClipboardMonitor} from './clipboard.js';
import {KlippaPopup} from './popup.js';

const HOTKEY = 'hotkey';

export default class KlippaExtension extends Extension {
    enable() {
        this._settings = this.getSettings();

        this._client = new KlippaClient();
        this._client.connectDaemon();

        this._monitor = new ClipboardMonitor(this._client);
        this._monitor.enable();

        this._popup = new KlippaPopup(this._client, this._settings);

        this._bindHotkey();
        // перепривязка при изменении хоткея (его синхронизирует демон, DMN-010)
        this._hotkeyChangedId =
            this._settings.connect(`changed::${HOTKEY}`, () => this._rebindHotkey());
    }

    disable() {
        if (this._hotkeyChangedId)
            this._settings.disconnect(this._hotkeyChangedId);
        Main.wm.removeKeybinding(HOTKEY);

        this._popup?.destroy();
        this._monitor?.disable();
        this._client?.destroy();

        this._settings = null;
        this._client = null;
        this._monitor = null;
        this._popup = null;
        this._hotkeyChangedId = 0;
    }

    _bindHotkey() {
        Main.wm.addKeybinding(
            HOTKEY,
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => this._popup.toggle());
    }

    _rebindHotkey() {
        Main.wm.removeKeybinding(HOTKEY);
        this._bindHotkey();
    }
}
