// D-Bus-клиент к демону klippad (org.klippa.Daemon).
// Тонкая обёртка над Gio.DBusProxy: асинхронные вызовы, подписка на
// HistoryChanged, мягкая деградация при недоступном демоне.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const BUS_NAME = 'org.klippa.Daemon';
const OBJECT_PATH = '/org/klippa/Daemon';

// Должно совпадать с docs/dbus-interface.xml (контракт IPC-001).
const IFACE_XML = `
<node>
  <interface name="org.klippa.Daemon1">
    <method name="Capture">
      <arg name="kind" type="s" direction="in"/>
      <arg name="data" type="ay" direction="in"/>
      <arg name="source_app" type="s" direction="in"/>
      <arg name="ts" type="x" direction="in"/>
      <arg name="sensitive" type="b" direction="in"/>
    </method>
    <method name="GetHistory">
      <arg name="limit" type="u" direction="in"/>
      <arg name="json" type="s" direction="out"/>
    </method>
    <method name="GetThumbnail">
      <arg name="id" type="t" direction="in"/>
      <arg name="png" type="ay" direction="out"/>
    </method>
    <method name="GetContent">
      <arg name="id" type="t" direction="in"/>
      <arg name="kind" type="s" direction="out"/>
      <arg name="data" type="ay" direction="out"/>
    </method>
    <method name="Promote"><arg name="id" type="t" direction="in"/></method>
    <method name="Delete"><arg name="id" type="t" direction="in"/></method>
    <method name="Clear"/>
    <signal name="HistoryChanged"/>
  </interface>
</node>`;

const KlippaProxy = Gio.DBusProxy.makeProxyWrapper(IFACE_XML);

export class KlippaClient {
    constructor() {
        this._proxy = null;
        this._signalId = 0;
        this._onChanged = null;
    }

    connectDaemon() {
        try {
            this._proxy = KlippaProxy(Gio.DBus.session, BUS_NAME, OBJECT_PATH);
        } catch (e) {
            logError(e, 'klippa: не удалось подключиться к демону');
            this._proxy = null;
        }
    }

    get available() {
        return this._proxy !== null;
    }

    // callback вызывается без аргументов при HistoryChanged.
    onHistoryChanged(callback) {
        this._onChanged = callback;
        if (this._proxy) {
            this._signalId = this._proxy.connectSignal(
                'HistoryChanged', () => this._onChanged?.());
        }
    }

    // --- захват -------------------------------------------------------------

    capture(kind, dataBytes, sourceApp, sensitive) {
        if (!this._proxy)
            return;
        const ts = GLib.DateTime.new_now_local().to_unix();
        // dataBytes — Uint8Array; GJS маршалит в 'ay'.
        this._proxy.CaptureRemote(
            kind, dataBytes, sourceApp ?? '', ts, !!sensitive,
            (_res, err) => { if (err) logError(err, 'klippa: Capture'); });
    }

    // --- чтение (async через Promise) --------------------------------------

    getHistory(limit = 0) {
        return new Promise(resolve => {
            if (!this._proxy)
                return resolve([]);
            this._proxy.GetHistoryRemote(limit, (res, err) => {
                if (err) {
                    logError(err, 'klippa: GetHistory');
                    return resolve([]);
                }
                try {
                    resolve(JSON.parse(res[0]));
                } catch (e) {
                    logError(e, 'klippa: разбор истории');
                    resolve([]);
                }
            });
        });
    }

    getThumbnail(id) {
        return new Promise(resolve => {
            if (!this._proxy)
                return resolve(null);
            this._proxy.GetThumbnailRemote(id, (res, err) => {
                if (err || !res[0] || res[0].length === 0)
                    return resolve(null);
                resolve(res[0]);  // Uint8Array (PNG)
            });
        });
    }

    getContent(id) {
        return new Promise(resolve => {
            if (!this._proxy)
                return resolve(null);
            this._proxy.GetContentRemote(id, (res, err) => {
                if (err) {
                    logError(err, 'klippa: GetContent');
                    return resolve(null);
                }
                resolve({kind: res[0], data: res[1]});  // data: Uint8Array
            });
        });
    }

    promote(id) {
        this._proxy?.PromoteRemote(id, () => {});
    }

    delete(id) {
        this._proxy?.DeleteRemote(id, () => {});
    }

    clear() {
        this._proxy?.ClearRemote(() => {});
    }

    destroy() {
        if (this._proxy && this._signalId)
            this._proxy.disconnectSignal(this._signalId);
        this._signalId = 0;
        this._onChanged = null;
        this._proxy = null;
    }
}
