import urwid

class MenuButton(urwid.Button):
    def __init__(self, caption, callback):
        super().__init__("Urwid integration is still in active development")
        urwid.connect_signal(self, 'click', callback)
        self._w = urwid.AttrMap(urwid.SelectableIcon(
            ['  \N{BULLET} ', caption], 2), None, 'selected')
