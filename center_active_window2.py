#!/usr/bin/env python3

# https://askubuntu.com/questions/832720/how-can-i-center-a-window-with-a-keyboard-shortcut

import gi
gi.require_version('Wnck', '3.0')
from gi.repository import Wnck, Gdk

screen = Wnck.Screen.get_default()
screen.force_update()
w=screen.get_width()
h=screen.get_height()

for window in screen.get_windows():
	if window.is_active() == True:
		window.unmaximize()

		x=window.get_geometry().xp
		y=window.get_geometry().yp
		width=window.get_geometry().widthp
		height=window.get_geometry().heightp

		monitor_center_x = w/2
		monitor_center_y = h/2

		new_position_x = monitor_center_x - width/2
		new_position_y = monitor_center_y - height/2

		window.set_geometry(0,Wnck.WindowMoveResizeMask(3),new_position_x,new_position_y,width,height)

window = None
screen = None
Wnck.shutdown()
