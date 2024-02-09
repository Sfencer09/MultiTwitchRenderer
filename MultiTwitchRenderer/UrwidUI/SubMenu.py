import urwid


from . import MenuButton, ActionChoice, HorizontalBoxes

class SubMenu(urwid.WidgetWrap):
    def __init__(self, top:HorizontalBoxes, caption, choices):
        super().__init__(MenuButton(
            [caption, "\N{HORIZONTAL ELLIPSIS}"], self.open_menu))
        line = urwid.Divider('\N{LOWER ONE QUARTER BLOCK}')
        listbox = urwid.Pile(urwid.SimpleFocusListWalker([
            urwid.AttrMap(urwid.Text(["\n  ", caption]), 'heading'),
            urwid.AttrMap(line, 'line'),
            urwid.Divider()] + choices + [ActionChoice('Close menu', closeTopBox),
                                          urwid.Divider()]))
        self.menu = urwid.AttrMap(listbox, 'options')

    def open_menu(self, button):
        self.top.open_box(self.menu)

