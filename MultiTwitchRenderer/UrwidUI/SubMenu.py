from typing import Callable
import urwid

from MultiTwitchRenderer.UrwidUI.UrwidUtils import expandChoices


from . import MenuButton, ActionChoice, HorizontalBoxes

class SubMenu(urwid.WidgetWrap):
    def __init__(self, caption:str, choices:Callable|list|tuple, *args, **kwargs):
        super().__init__(MenuButton(
            [caption, "\N{HORIZONTAL ELLIPSIS}"], self.open_menu))
        self.__caption = caption
        self.choices = choices
        self.choices_args = args
        self.choices_kwargs = kwargs

    def open_menu(self, button):
        #self.top.open_box(self.menu)
        line = urwid.Divider('\N{LOWER ONE QUARTER BLOCK}')
        choiceList = expandChoices(self.choices, *self.choices_args, **self.choices_kwargs)
        listbox = urwid.Pile(urwid.SimpleFocusListWalker([
            urwid.AttrMap(urwid.Text(["\n  ", self.__caption]), 'heading'),
            urwid.AttrMap(line, 'line'),
            urwid.Divider()] + choiceList + [ActionChoice('Close menu', HorizontalBoxes.closeTopBox),
                                          urwid.Divider()]))
        self.menu = urwid.AttrMap(listbox, 'options')
        HorizontalBoxes.openTopBox(self.menu)

