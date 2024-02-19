from typing import Callable
import urwid

from MultiTwitchRenderer.UrwidUI.HorizontalBoxes import closeTopBox, openTopBox
from MultiTwitchRenderer.UrwidUI.UrwidUtils import expandChoices

from . import MenuButton, ActionChoice

class PagedMenu(urwid.WidgetWrap):
    def __init__(self, caption: str, choices: Callable|list|tuple, pageHeight=10, pageWidth=3, *choices_args, **choices_kwargs):
        super().__init__(MenuButton(
            [caption, "\N{HORIZONTAL ELLIPSIS}"], self.open_menu))
        self.menu = None
        self.listbox = None
        self.line = urwid.Divider('\N{LOWER ONE QUARTER BLOCK}')
        self.nextPageOption = MenuButton('Next page', self.next_page)
        self.prevPageOption = MenuButton('Previous page', self.prev_page)
        self.choices = choices
        self.pageNum = 0
        self.pageWidth = pageWidth
        self.pageHeight = pageHeight
        self.pageSize = pageWidth * pageHeight
        self.choices_args = choices_args
        self.choices_kwargs = choices_kwargs

    def _get_current_page(self):
        options = expandChoices(self.choices, *self.choices_args, **self.choices_kwargs)
        page = options[self.pageNum *
                       self.pageSize: (self.pageNum+1)*self.pageSize]
        return page

    def open_menu(self, button):
        currentPage = self._get_current_page()
        self.listbox = urwid.Pile(urwid.SimpleFocusListWalker([
            urwid.AttrMap(urwid.Text(["\n  ", self.caption]), 'heading'),
            urwid.AttrMap(self.line, 'line'),
            urwid.Divider()] + currentPage + [ActionChoice('Close menu', closeTopBox),
                                              urwid.Divider()]))
        self.menu = urwid.AttrMap(self.listbox, 'options')
        openTopBox(self.menu)

    def next_page(self):
        self.pageNum += 1
        #top.close_box()
        closeTopBox()
        self.open_menu(None)
        # top.open_box(self.menu)

    def prev_page(self):
        self.pageNum -= 1
        #top.close_box()
        closeTopBox()
        self.open_menu(None)
        # top.open_box(self.menu)
