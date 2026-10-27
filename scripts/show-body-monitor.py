#!/usr/bin/env python3
"""Local display for the Raspberry monitor; requires its SSH tunnel on 8765."""
import gi
gi.require_version('Gtk','3.0')
gi.require_version('WebKit2','4.1')
from gi.repository import Gtk,Gdk,WebKit2
window=Gtk.Window(title='Arka · Presença')
window.set_default_size(1920,1080)
view=WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral())
window.add(view)
window.connect('destroy',Gtk.main_quit)
window.show_all()
display=Gdk.Display.get_default()
for i in range(display.get_n_monitors()):
    monitor=display.get_monitor(i)
    if monitor.get_geometry().x==0:
        g=monitor.get_geometry();window.move(g.x,g.y)
        window.fullscreen_on_monitor(window.get_screen(),i)
        break
view.load_uri('http://127.0.0.1:8765/monitor')
Gtk.main()
