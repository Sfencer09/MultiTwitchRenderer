import urwid
import os
import threading
import time 
START_TIME = time.time()


class BufferedText(urwid.Text):
    def __init__(self, buffer_length=100, label='', *, wrap='any'):
        super().__init__("", align='left', wrap=wrap)
        self.buffer = []
        self.buffer_length = buffer_length
        self.label = label
        self.lock = threading.Lock()

    def addLine(self, line):  # function will likely be called by a different thread than the main thread that created it
        #if not URWID:
        #    if len(self.buffer) > 0:  # clear buffer in case of race conditions with URWID
        #        for b in self.buffer:
        #            print(b)
        #        self.buffer = []
        #    print(line)
        #    return
        self.lock.acquire()
        try:
            while len(self.buffer) >= self.buffer_length:
                del self.buffer[-1]
            formatted_line = f'[{self.label}{time.time()-START_TIME}] {line}'
            self.buffer.insert(0, formatted_line)
            self.set_text('\n'.join(self.buffer))
            global mainloopMessageBus
            # mainloopMessageBus.write(1)
            os.write(mainloopMessageBus, self.label.encode('utf-8'))
        finally:
            self.lock.release()

