// Всплывающее меню у курсора. На GNOME Wayland только код внутри shell может
// открыть окно в произвольной точке — поэтому popup рисуется здесь, а не в демоне.
//
// Функции: позиционирование у курсора с клампом в монитор, навигация только
// клавиатурой (стрелки/Enter/Esc/Delete), инкрементальный фильтр набором текста,
// миниатюры картинок, авто-вставка Ctrl+V в прежнее окно, живое обновление.

import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import GdkPixbuf from 'gi://GdkPixbuf';
import Cogl from 'gi://Cogl';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const PASTE_DELAY_MS = 60;   // дать фокусу вернуться прежнему окну до синтеза Ctrl+V

function thumbnailActor(pngBytes) {
    // PNG-байты → drawable St.Widget. При сбое — null (вызов сделает фолбэк).
    try {
        const loader = GdkPixbuf.PixbufLoader.new();
        loader.write_bytes(GLib.Bytes.new(pngBytes));
        loader.close();
        const pb = loader.get_pixbuf();
        const w = pb.get_width();
        const h = pb.get_height();
        const image = St.ImageContent.new_with_preferred_size(w, h);
        image.set_bytes(
            pb.read_pixel_bytes(),
            pb.get_has_alpha() ? Cogl.PixelFormat.RGBA_8888 : Cogl.PixelFormat.RGB_888,
            w, h, pb.get_rowstride());
        const widget = new St.Widget({style_class: 'klippa-thumb'});
        widget.set_content(image);
        widget.set_size(w, h);
        return widget;
    } catch (e) {
        logError(e, 'klippa: миниатюра');
        return null;
    }
}

export class KlippaPopup {
    constructor(client, settings) {
        this._client = client;
        this._settings = settings;
        this._actor = null;
        this._listBox = null;
        this._hintLabel = null;
        this._grab = null;
        this._isOpen = false;
        this._prevFocus = null;
        this._virtualKeyboard = null;   // создаётся лениво, переиспользуется
        this._entries = [];        // полная история (meta)
        this._filtered = [];       // после фильтра
        this._rows = [];           // актёры строк, соответствуют _filtered
        this._selected = 0;
        this._query = '';
        // живое обновление при открытом меню (EXT-012)
        this._client.onHistoryChanged(() => {
            if (this._isOpen)
                this._reload();
        });
    }

    toggle() {
        if (this._isOpen)
            this.close();
        else
            this.open();
    }

    open() {
        if (this._isOpen)
            return;
        this._prevFocus = global.display.focus_window;
        this._query = '';
        this._selected = 0;
        this._build();

        Main.layoutManager.uiGroup.add_child(this._actor);
        this._positionAtPointer();

        this._grab = Main.pushModal(this._actor, {actionMode: Shell.ActionMode.POPUP});
        this._actor.grab_key_focus();
        this._isOpen = true;
        this._reload();
    }

    close() {
        if (!this._isOpen)
            return;
        this._isOpen = false;
        if (this._grab) {
            Main.popModal(this._grab);
            this._grab = null;
        }
        if (this._actor) {
            this._actor.destroy();
            this._actor = null;
            this._listBox = null;
            this._hintLabel = null;
        }
        this._rows = [];
    }

    destroy() {
        this.close();
        this._virtualKeyboard = null;
        this._client = null;
        this._settings = null;
    }

    // --- построение UI ------------------------------------------------------

    _build() {
        this._actor = new St.BoxLayout({
            vertical: true,
            style_class: 'klippa-popup',
            reactive: true,
            can_focus: true,
        });
        this._actor.connect('key-press-event', this._onKeyPress.bind(this));
        // клик вне popup закрывает (модальный grab доставляет события сюда первым)
        this._actor.connect('captured-event', this._onCapturedEvent.bind(this));

        this._hintLabel = new St.Label({style_class: 'klippa-hint'});
        this._actor.add_child(this._hintLabel);

        this._listBox = new St.BoxLayout({vertical: true, style_class: 'klippa-list'});
        this._scroll = new St.ScrollView({style_class: 'klippa-scroll'});
        if (this._scroll.set_child)
            this._scroll.set_child(this._listBox);
        else
            this._scroll.add_actor(this._listBox);  // совместимость со старым St
        this._actor.add_child(this._scroll);
    }

    _positionAtPointer() {
        const [x, y] = global.get_pointer();
        // якорь у курсора и рабочая область монитора под курсором фиксируются
        // на время жизни popup; размеры окна меняются (асинхронная загрузка
        // истории, фильтрация), поэтому кламп пересчитываем при каждом релейауте.
        this._anchorX = x;
        this._anchorY = y;
        const idx = global.display.get_current_monitor();
        this._workArea = Main.layoutManager.getWorkAreaForMonitor(idx);
        this._actor.set_position(x, y);
        this._clamp();
        // повторный кламп после каждого изменения размера, чтобы окно с уже
        // наполненным/отфильтрованным списком не выходило за границы экрана
        this._actor.connect('notify::height', this._clamp.bind(this));
        this._actor.connect('notify::width', this._clamp.bind(this));
    }

    // держит окно как можно ближе к курсору, но в пределах рабочей области
    _clamp() {
        if (!this._actor || !this._workArea)
            return;
        const wa = this._workArea;
        const [w, h] = this._actor.get_size();
        let px = Math.min(this._anchorX, wa.x + wa.width - w);
        let py = Math.min(this._anchorY, wa.y + wa.height - h);
        px = Math.max(px, wa.x);
        py = Math.max(py, wa.y);
        this._actor.set_position(px, py);
    }

    // --- данные -------------------------------------------------------------

    async _reload() {
        const limit = this._settings?.get_int('popup-limit') ?? 50;
        this._entries = await this._client.getHistory(limit);
        this._applyFilter();
    }

    _applyFilter() {
        const q = this._query.toLowerCase();
        this._filtered = q
            ? this._entries.filter(e => (e.preview ?? '').toLowerCase().includes(q))
            : this._entries.slice();
        if (this._selected >= this._filtered.length)
            this._selected = Math.max(0, this._filtered.length - 1);
        this._render();
    }

    _render() {
        if (!this._listBox)
            return;
        this._listBox.destroy_all_children();
        this._rows = [];

        this._hintLabel.text = this._query
            ? `Поиск: ${this._query}`
            : 'Стрелки/мышь — выбор · Enter/клик — вставить · Del — удалить · Esc — выход';

        if (this._filtered.length === 0) {
            const empty = new St.Label({
                style_class: 'klippa-empty',
                text: this._entries.length === 0 ? 'История пуста' : 'Ничего не найдено',
            });
            this._listBox.add_child(empty);
            return;
        }

        this._filtered.forEach((entry, i) => {
            const row = new St.BoxLayout({
                style_class: 'klippa-row',
                vertical: false,
                reactive: true,
                track_hover: true,
            });
            // наведение мышью подсвечивает строку (синхронно с клавиатурой)
            row.connect('notify::hover', () => {
                if (row.hover && this._selected !== i) {
                    this._selected = i;
                    this._updateSelection();
                }
            });
            // клик по строке — выбрать и вставить (как Enter)
            row.connect('button-release-event', () => {
                this._selected = i;
                this._activate();
                return Clutter.EVENT_STOP;
            });
            row.add_child(new St.Label({
                style_class: 'klippa-index',
                text: `${i + 1}`,
            }));
            if (entry.kind === 'image' && entry.has_image) {
                this._attachImageRow(row, entry);
            } else {
                row.add_child(new St.Label({
                    style_class: 'klippa-text',
                    text: entry.preview ?? '',
                }));
            }
            this._listBox.add_child(row);
            this._rows.push(row);
        });
        this._updateSelection();
    }

    _attachImageRow(row, entry) {
        const label = new St.Label({style_class: 'klippa-text', text: entry.preview ?? '[изображение]'});
        row.add_child(label);
        // подгрузка миниатюры асинхронно
        this._client.getThumbnail(entry.id).then(png => {
            if (!png || !this._isOpen)
                return;
            const thumb = thumbnailActor(png);
            if (thumb)
                row.insert_child_at_index(thumb, 1);
        });
    }

    _updateSelection() {
        this._rows.forEach((row, i) => {
            if (i === this._selected)
                row.add_style_class_name('klippa-selected');
            else
                row.remove_style_class_name('klippa-selected');
        });
    }

    // --- клавиатура ---------------------------------------------------------

    _onCapturedEvent(_actor, event) {
        // Закрыть при нажатии мыши/тача вне области popup. Внутри (по строке или
        // фону) — пропускаем, чтобы сработали обработчики строк. Паттерн взят из
        // PopupMenuManager штатного Shell (global.stage.get_event_actor + contains).
        const type = event.type();
        if (type === Clutter.EventType.BUTTON_PRESS ||
            type === Clutter.EventType.TOUCH_BEGIN) {
            const target = global.stage.get_event_actor(event);
            if (this._actor && !this._actor.contains(target)) {
                this.close();
                return Clutter.EVENT_STOP;
            }
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _onKeyPress(_actor, event) {
        const symbol = event.get_key_symbol();

        switch (symbol) {
        case Clutter.KEY_Escape:
            this.close();
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Up:
            this._move(-1);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Down:
            this._move(1);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Return:
        case Clutter.KEY_KP_Enter:
            this._activate();
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Delete:
            this._deleteSelected();
            return Clutter.EVENT_STOP;
        case Clutter.KEY_BackSpace:
            if (this._query.length > 0) {
                this._query = this._query.slice(0, -1);
                this._applyFilter();
            }
            return Clutter.EVENT_STOP;
        }

        // печатаемый символ → инкрементальный фильтр
        const ch = event.get_key_unicode();
        if (ch && ch.length > 0 && ch.charCodeAt(0) >= 0x20) {
            this._query += ch;
            this._applyFilter();
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _move(delta) {
        if (this._filtered.length === 0)
            return;
        this._selected =
            (this._selected + delta + this._filtered.length) % this._filtered.length;
        this._updateSelection();
        this._ensureVisible();
    }

    _ensureVisible() {
        // прокрутка к выбранной строке (best-effort через vadjustment ScrollView)
        const row = this._rows[this._selected];
        const adj = this._scroll?.vadjustment
            ?? this._scroll?.get_vadjustment?.();
        if (row && adj) {
            const box = row.get_allocation_box();
            if (box.y1 < adj.value)
                adj.value = box.y1;
            else if (box.y2 > adj.value + adj.page_size)
                adj.value = box.y2 - adj.page_size;
        }
    }

    // --- действия -----------------------------------------------------------

    async _activate() {
        const entry = this._filtered[this._selected];
        if (!entry)
            return;
        this._client.promote(entry.id);
        const content = await this._client.getContent(entry.id);
        const autoPaste = this._settings?.get_boolean('auto-paste') ?? true;
        this.close();
        if (!content)
            return;
        this._setClipboard(content);
        if (autoPaste)
            this._pasteIntoPrevious();
    }

    _setClipboard(content) {
        const cb = St.Clipboard.get_default();
        if (content.kind === 'text') {
            const text = new TextDecoder().decode(content.data);
            cb.set_text(St.ClipboardType.CLIPBOARD, text);
        } else {
            cb.set_content(
                St.ClipboardType.CLIPBOARD, 'image/png', GLib.Bytes.new(content.data));
        }
    }

    _pasteIntoPrevious() {
        // фокус уже вернулся прежнему окну после popModal; синтезируем Ctrl+V
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, PASTE_DELAY_MS, () => {
            try {
                if (!this._virtualKeyboard) {
                    const seat = Clutter.get_default_backend().get_default_seat();
                    this._virtualKeyboard = seat.create_virtual_device(
                        Clutter.InputDeviceType.KEYBOARD_DEVICE);
                }
                const vk = this._virtualKeyboard;
                // notify_keyval ждёт МИКРОсекунды (как keyboard.js самого Shell),
                // а get_current_event_time() — миллисекунды. Без ×1000 таймстамп
                // оказывается «в прошлом», и компоситор отбрасывает синтезированные
                // нажатия — буфер ставится, но Ctrl+V не доходит до окна.
                const t = Clutter.get_current_event_time() * 1000;
                vk.notify_keyval(t, Clutter.KEY_Control_L, Clutter.KeyState.PRESSED);
                vk.notify_keyval(t, Clutter.KEY_v, Clutter.KeyState.PRESSED);
                vk.notify_keyval(t, Clutter.KEY_v, Clutter.KeyState.RELEASED);
                vk.notify_keyval(t, Clutter.KEY_Control_L, Clutter.KeyState.RELEASED);
            } catch (e) {
                logError(e, 'klippa: авто-вставка');
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _deleteSelected() {
        const entry = this._filtered[this._selected];
        if (!entry)
            return;
        this._client.delete(entry.id);
        // оптимистично убираем локально; HistoryChanged подтвердит
        this._entries = this._entries.filter(e => e.id !== entry.id);
        this._applyFilter();
    }
}
