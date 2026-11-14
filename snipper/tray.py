"""Tray icon via StatusNotifierItem + com.canonical.dbusmenu, implemented on raw GDBus.

GTK4 has no tray API; Ubuntu ships the AppIndicator/KStatusNotifierItem extension, which
speaks this protocol. If no watcher is running the tray is silently skipped.
"""
from __future__ import annotations

import os

from gi.repository import Gio, GLib

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parent"/></signal>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
  </interface>
</node>
"""


class Tray:
    def __init__(self, app_id, icon_name, icon_theme_path, items, on_activate):
        """items: list of (label, callback) or None for a separator."""
        self.app_id = app_id
        self.icon_name = icon_name
        self.icon_theme_path = icon_theme_path or ""
        self.on_activate = on_activate
        self.items = {}
        self.order = []
        for i, item in enumerate(items, start=1):
            self.items[i] = item
            self.order.append(i)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._regs = []
        self._name_id = 0
        self.service = f"org.kde.StatusNotifierItem-{os.getpid()}-1"

    def start(self) -> bool:
        try:
            sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
            menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
            self._regs.append(self.bus.register_object(
                "/StatusNotifierItem", sni, self._sni_call, self._sni_prop, None))
            self._regs.append(self.bus.register_object("/MenuBar", menu, self._menu_call, self._menu_prop, None))
        except GLib.Error as e:
            print("snipper: tray unavailable:", e.message)
            return False
        self._name_id = Gio.bus_own_name_on_connection(
            self.bus, self.service, Gio.BusNameOwnerFlags.NONE, self._on_name, None)
        return True

    def _on_name(self, *_):
        self._register_with_watcher()
        # re-register when the watcher (shell extension) restarts
        Gio.bus_watch_name_on_connection(
            self.bus, "org.kde.StatusNotifierWatcher", Gio.BusNameWatcherFlags.NONE,
            lambda *a: self._register_with_watcher(), None)

    def _register_with_watcher(self):
        self.bus.call(
            "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
            "RegisterStatusNotifierItem", GLib.Variant("(s)", (self.service,)), None,
            Gio.DBusCallFlags.NONE, -1, None, self._registered,
        )

    def _registered(self, bus, res):
        try:
            bus.call_finish(res)
        except GLib.Error:
            pass  # no tray host; shortcuts still work

    def stop(self):
        for r in self._regs:
            self.bus.unregister_object(r)
        self._regs = []
        if self._name_id:
            Gio.bus_unown_name(self._name_id)
            self._name_id = 0

    # StatusNotifierItem ------------------------------------------------------
    def _sni_prop(self, conn, sender, path, iface, prop):
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", "Snipper"),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", self.icon_name),
            "IconThemePath": GLib.Variant("s", self.icon_theme_path),
            "Menu": GLib.Variant("o", "/MenuBar"),
            "ItemIsMenu": GLib.Variant("b", False),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "Snipper", "Klik untuk capture area")),
        }
        return values.get(prop)

    def _sni_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "Activate":
            GLib.idle_add(lambda: (self.on_activate(), False)[1])
        invocation.return_value(None)

    # dbusmenu ----------------------------------------------------------------
    def _item_props(self, item_id):
        if item_id == 0:
            return {"children-display": GLib.Variant("s", "submenu")}
        item = self.items[item_id]
        if item is None:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", item[0]), "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True)}

    def _layout(self, item_id):
        children = []
        if item_id == 0:
            children = [GLib.Variant("(ia{sv}av)", self._layout(i)) for i in self.order]
        return (item_id, self._item_props(item_id), children)

    def _menu_prop(self, conn, sender, path, iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", [self.icon_theme_path] if self.icon_theme_path else []),
        }.get(prop)

    def _menu_call(self, conn, sender, path, iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent = args[0]
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, self._layout(parent if parent in (0, *self.items) else 0))))
        elif method == "GetGroupProperties":
            ids = args[0] or [0, *self.order]
            out = [(i, self._item_props(i)) for i in ids if i == 0 or i in self.items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
        elif method == "GetProperty":
            props = self._item_props(args[0]) if args[0] == 0 or args[0] in self.items else {}
            invocation.return_value(GLib.Variant("(v)", (props.get(args[1], GLib.Variant("s", "")),)))
        elif method == "Event":
            self._event(args[0], args[1])
            invocation.return_value(None)
        elif method == "EventGroup":
            for ev in args[0]:
                self._event(ev[0], ev[1])
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _event(self, item_id, event_id):
        if event_id != "clicked":
            return
        item = self.items.get(item_id)
        if item:
            GLib.idle_add(lambda: (item[1](), False)[1])
