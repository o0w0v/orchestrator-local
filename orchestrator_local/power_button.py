"""Vector power control with a state ring and keyboard operation; no image assets."""
import tkinter as tk


class PowerButton(tk.Canvas):
    SIZE = 220
    ON_RING = '#22a45a'
    OFF_RING = '#cbd2dc'

    def __init__(self, parent, command, background='#f3f5f9'):
        super().__init__(parent, width=self.SIZE, height=self.SIZE, bg=background,
                         highlightthickness=0, borderwidth=0, takefocus=True)
        self.command = command
        self.is_on = False
        self.action_label = 'ONにする'
        self.disabled = False
        self.hover = False
        self.focused = False
        self.pressed = False
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Motion>', self._motion)
        self.bind('<Leave>', lambda _: self._leave())
        self.bind('<FocusIn>', lambda _: self._focus(True))
        self.bind('<FocusOut>', lambda _: self._focus(False))
        self.bind('<KeyRelease-Return>', self._key)
        self.bind('<KeyRelease-space>', self._key)
        self.draw()

    def __getitem__(self, key):
        return self.action_label if key == 'text' else super().__getitem__(key)

    def destroy(self):
        self.command = None
        super().destroy()

    def set_value(self, enabled, action_label):
        self.is_on = bool(enabled)
        self.action_label = action_label
        self.draw()

    def state(self, flags=None):
        if flags is not None:
            if 'disabled' in flags: self.disabled = True
            if '!disabled' in flags: self.disabled = False
            if self.disabled: self.pressed = False
            self.draw()
        return ('disabled',) if self.disabled else ()

    def invoke(self):
        if not self.disabled:
            return self.command()

    def _inside(self, event):
        return (event.x-110)**2 + (event.y-110)**2 <= 92**2

    def _press(self, event):
        if not self.disabled and self._inside(event):
            self.focus_set(); self.pressed = True; self.draw()

    def _release(self, event):
        activate = self.pressed and self._inside(event)
        self.pressed = False; self.draw()
        if activate: self.invoke()

    def _motion(self, event):
        hover = self._inside(event)
        if hover != self.hover:
            self.hover = hover; self.draw()

    def _leave(self):
        self.hover = False; self.pressed = False; self.draw()

    def _focus(self, value):
        self.focused = value; self.draw()

    def _key(self, _):
        self.invoke()
        return 'break'

    def draw(self):
        self.delete('all')
        ring = self.ON_RING if self.is_on else self.OFF_RING
        halo = '#e0f5e9' if self.is_on else '#e9edf2'
        icon = '#157b40' if self.is_on else '#657387'
        face = '#f0fbf4' if self.is_on else '#ffffff'
        if (self.hover or self.pressed) and not self.disabled:
            face = '#ddf5e7' if self.is_on else '#f4f6f9'
        self.configure(cursor='hand2' if self.hover and not self.disabled else 'arrow')
        self.create_oval(10, 10, 210, 210, fill=halo, outline='', tags='halo')
        self.create_oval(20, 20, 200, 200, fill=face, outline=ring, width=7, tags='ring')
        self.create_arc(82, 74, 138, 130, start=130, extent=280, style='arc',
                        outline=icon, width=6, tags='power')
        self.create_line(110, 64, 110, 98, fill=icon, width=6, capstyle='round', tags='power')
        self.create_text(110, 157, text='ON' if self.is_on else 'OFF',
                         font=('Segoe UI', 17, 'bold'), fill=icon, tags='state_label')
        if self.focused:
            self.create_oval(3, 3, 217, 217, outline='#2563eb', width=2,
                             dash=(3, 4), tags='focus')
