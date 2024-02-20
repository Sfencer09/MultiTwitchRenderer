import urwid

from . import BufferedText, SubMenu, InfoChoice, HorizontalBoxes, ActionChoice

if __debug__:
    from config import *
exec(open("config.py").read(), globals())
from RenderWorker import endRendersAndExit, renderThread
if COPY_FILES:
    from CopyWorker import copyThread


def exit_program(button):
    raise urwid.ExitMainLoop()

# Text Widgets


def renderThreadChoice(key):
    if renderThread.nativeId is None:
        renderThread.start()


class RenderThreadStatusString:
    def __str__(self):
        started = renderThread.nativeId is not None
        return 'Render thread already started!' if started else 'Starting render thread!'

if ENABLE_URWID:
    btLabels = ['S', 'R']
    if COPY_FILES:
        btLabels.insert(1, 'C')

    bufferedTexts = [BufferedText(label=label) for label in btLabels]

    if COPY_FILES:
        sessionText, copyText, renderText = bufferedTexts
    else:
        sessionText, renderText = bufferedTexts


def urwidUiMain():
    # Pile for Text Widgets
    btFillers = [urwid.Filler(bt, 'top') for bt in bufferedTexts]

    # Columns for Text Widgets
    # columns = urwid.Columns([left_filler, right_filler])
    columns = urwid.Columns(btFillers)

    divider = urwid.Divider('=')

    menu_top = SubMenu('Main Menu', [
        # SubMenu('Applications', [
        #    SubMenu('Accessories', [
        #        InfoChoice('Text Editor', closeTopBox, 'Text Editor'),
        #        InfoChoice('Terminal', closeTopBox, 'testFunc1'),
        #        ActionChoice('Close menu', closeTopBox)
        #    ]),
        #    ActionChoice('Close menu', closeTopBox)
        # ]),
        # SubMenu('System', [
        #    SubMenu('Preferences', [
        #        InfoChoice('Appearance', closeTopBox, 'Appearance'),
        #        ActionChoice('Close menu', closeTopBox)
        #    ]),
        #    InfoChoice('Lock Screen', exit_program, 'Lock Screen'.encode()),
        #    ActionChoice('Close menu', closeTopBox)
        # ]),
        ActionChoice('Exit program', endRendersAndExit if 'endRendersAndExit' in globals(
        ).keys() else exit_program),
        InfoChoice('Start render thread', renderThreadChoice,
                RenderThreadStatusString()),
        # InfoChoice('Print active jobs', activeJobsChoice, ),
        # InfoChoice('Print queued jobs'),
        # InfoChoice('Print completed jobs'),
        # InfoChoice('Print errored jobs'),
        # ActionChoice('Clean up errored jobs'),
        # PagedMenu('Edit queue(s)')
        # InfoChoice('')
    ])

    palette = [
        (None,  'light gray', 'black'),
        ('heading', 'black', 'light gray'),
        ('line', 'black', 'light gray'),
        ('options', 'dark gray', 'black'),
        ('focus heading', 'white', 'dark red'),
        ('focus line', 'black', 'dark red'),
        ('focus options', 'black', 'light gray'),
        ('selected', 'white', 'dark blue')]
    

    HorizontalBoxes.top_menu.open_box(menu_top.menu)

    vbox = urwid.Pile([columns, ('pack', divider), ('pack', HorizontalBoxes.top_menu)])

    # urwid.MainLoop(urwid.Filler(top, 'middle', 10), palette).run()

    mainloop = urwid.MainLoop(vbox, palette)

    def messageBusReceiverV1(data: bytes):
        # use first byte to look up label, then parse rest as data
        raise Exception('not implemented')
        return True

    def messageBusReceiverV2(data: bytes):
        # ignore data, simply use it as a callback to trigger draw_screen()
        mainloop.draw_screen()

    global mainloopMessageBus
    mainloopMessageBus = mainloop.watch_pipe(messageBusReceiverV2)
    
    mainloop.run()