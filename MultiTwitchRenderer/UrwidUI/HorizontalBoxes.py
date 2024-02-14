import urwid

focus_map = {
    'heading': 'focus heading',
    'options': 'focus options',
    'line': 'focus line'}


def closeTopBox(button) -> None:
    top_menu.close_box()

def openTopBox(box) -> None:
    top_menu.open_box(box)

class HorizontalBoxes(urwid.Columns):
    def __init__(self):
        super().__init__([], dividechars=1)

    def open_box(self, box):
        if self.contents:
            del self.contents[self.focus_position + 1:]
        self.contents.append((urwid.AttrMap(box, 'options', focus_map),
                              self.options('given', 24)))
        self.focus_position = len(self.contents) - 1

    def close_box(self):
        if self.contents:
            del self.contents[self.focus_position:]
        self.focus_position = len(self.contents) - 1

def getTopMenu() -> HorizontalBoxes:
    return top_menu

top_menu = HorizontalBoxes()
