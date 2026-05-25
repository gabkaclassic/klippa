// Захват буфера обмена внутри gnome-shell — единственный надёжный способ на
// Wayland (внешний процесс не видит буфер в фоне).
//
// Подписываемся на сигнал owner-changed у Meta.Selection (без polling), читаем
// содержимое через St.Clipboard, определяем тип по MIME и пересылаем демону.

import St from 'gi://St';
import Meta from 'gi://Meta';
import GLib from 'gi://GLib';

// MIME-подсказки, которыми менеджеры паролей помечают «не сохранять».
const SECRET_HINTS = [
    'x-kde-passwordManagerHint',
    'application/x-kde-passwordManagerHint',
    'x-kde-passwordmanagerhint',
];

const PREFERRED_IMAGE_MIME = 'image/png';

export class ClipboardMonitor {
    constructor(client) {
        this._client = client;
        this._selection = null;
        this._ownerChangedId = 0;
        this._clipboard = St.Clipboard.get_default();
        this._lastText = null;        // дебаунс повторных одинаковых событий
    }

    enable() {
        this._selection = global.display.get_selection();
        this._ownerChangedId = this._selection.connect(
            'owner-changed', (_sel, type, _source) => {
                if (type === Meta.SelectionType.SELECTION_CLIPBOARD)
                    this._onClipboardChanged();
            });
    }

    disable() {
        if (this._selection && this._ownerChangedId)
            this._selection.disconnect(this._ownerChangedId);
        this._selection = null;
        this._ownerChangedId = 0;
        this._lastText = null;
    }

    _sourceApp() {
        const win = global.display.focus_window;
        return win ? (win.get_wm_class() ?? '') : '';
    }

    _onClipboardChanged() {
        const mimetypes = this._clipboard.get_mimetypes(St.ClipboardType.CLIPBOARD) ?? [];

        // EXT-009: не захватываем помеченное менеджерами паролей.
        const sensitive = mimetypes.some(
            m => SECRET_HINTS.includes(m.toLowerCase?.() ?? m));
        if (sensitive)
            return;

        // EXT-008: предпочитаем изображение, если оно есть в буфере.
        const imageMime = this._pickImageMime(mimetypes);
        if (imageMime) {
            this._captureImage(imageMime);
            return;
        }
        this._captureText();
    }

    _pickImageMime(mimetypes) {
        if (mimetypes.includes(PREFERRED_IMAGE_MIME))
            return PREFERRED_IMAGE_MIME;
        return mimetypes.find(m => m.startsWith('image/')) ?? null;
    }

    _captureText() {
        this._clipboard.get_text(St.ClipboardType.CLIPBOARD, (_cb, text) => {
            if (!text || text === this._lastText)
                return;
            this._lastText = text;
            const bytes = new TextEncoder().encode(text);
            this._client.capture('text', bytes, this._sourceApp(), false);
        });
    }

    _captureImage(mime) {
        this._clipboard.get_content(St.ClipboardType.CLIPBOARD, mime, (_cb, bytes) => {
            if (!bytes)
                return;
            const data = bytes.get_data?.() ?? bytes;
            if (!data || data.length === 0)
                return;
            this._lastText = null;  // картинка сбрасывает текстовый дебаунс
            // Демон ждёт PNG; большинство приложений и скриншоты дают image/png.
            // Прочие форматы передаём как есть — демон сам валидирует/отбросит.
            this._client.capture('image', data, this._sourceApp(), false);
        });
    }
}
