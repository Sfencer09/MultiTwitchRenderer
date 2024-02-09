import urwid

import MenuButton

class ActionChoice(urwid.WidgetWrap):
    def __init__(self, caption, callback):
        super().__init__(
            MenuButton(caption, self.item_chosen))
        self.caption = caption
        self.callback = callback

    def item_chosen(self, button):
        self.callback(button)
        # response = urwid.Text(['  You chose ', self.caption, '\n'])
        # done = MenuButton('Ok', self.callback)
        # response_box = urwid.Pile([response, done])
        # top.open_box(urwid.AttrMap(response_box, 'options'))
