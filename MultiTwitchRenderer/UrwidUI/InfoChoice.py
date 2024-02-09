from typing import Any
import urwid

import MenuButton


class InfoChoice(urwid.WidgetWrap):
    def __init__(self, caption: str, callback: Any, text: Any):
        super().__init__(
            MenuButton(caption, self.item_chosen))
        self.caption = caption
        self.callback = callback
        self.text = text

    def item_chosen(self, button):
        if type(self.text) == str:
            message = self.text
        elif type(self.text) == bytes:
            message = self.text.decode()
        elif callable(self.text):
            message = self.text()
        else:
            message = str(self.text)
        # response = urwid.Text(['  You chose ', self.caption, '\n'])
        response = urwid.Text(message+'\n')
        done = MenuButton('Ok', self.callback)
        response_box = urwid.Pile([response, done])
        top.open_box(urwid.AttrMap(response_box, 'options'))

