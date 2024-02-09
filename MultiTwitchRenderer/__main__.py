from datetime import timedelta
import threading
import sys
import os
from CommandWorker import commandWorker
from MultiTwitchRenderer import calcGameCounts
from SessionWorker import sessionWorker
from UrwidUI.UrwidMain import urwidUiMain

import config

from RenderConfig import RenderConfig
from RenderWorker import renderWorker, renderThread
if config.COPY_FILES:
    from CopyWorker import copyWorker, copyThread

os.makedirs(config.logFolder, exist_ok=True)
if config.COPY_FILES:
    assert config.localBasepath.strip(' /\\') != config.basepath.strip(' /\\')

if config.ENABLE_URWID:
    import UrwidUI.UrwidMain
    renderThread = threading.Thread(target=renderWorker, kwargs={'renderLog':UrwidUI.UrwidMain.renderText.addLine})
    renderThread.daemon = True
    if config.COPY_FILES:
        copyThread = threading.Thread(target=copyWorker, kwargs={'copyLog':UrwidUI.UrwidMain.copyText.addLine})
        copyThread.daemon = True
else:
    renderThread = threading.Thread(target=renderWorker)
    renderThread.daemon = True
    if config.COPY_FILES:
        copyThread = threading.Thread(target=copyWorker)
        copyThread.daemon = True

def mainStart():
    if config.ENABLE_URWID:
        try:
            urwidUiMain()
        except TypeError as ex:
            if str(ex) == 'ord() expected a character, but string of length 0 found':
                URWID = False
                print(
                    "Unable to start urwid loop, possibly in Jupyter Notebook?\nFalling back to simple terminal control!")
                commandWorker()
            else:
                raise ex
    else:
        commandWorker()




if __name__ == '__main__':
    defaultSessionRenderConfig = RenderConfig()
    
    if not __debug__:
        print("Deployment mode")
        if config.COPY_FILES:
            copyThread.start()
        # renderThread.start()
        sessionThread = threading.Thread(target=sessionWorker, kwargs={'renderConfig': defaultSessionRenderConfig,
                                                                       'maxLookback': timedelta(days=config.DEFAULT_LOOKBACK_DAYS)})
        sessionThread.daemon = True
        sessionThread.start()
        if config.ENABLE_URWID:
            mainStart()
        else:
            commandWorker()
        sys.exit(0)
    else:
        print("Development mode")
        devSessionRenderConfig = defaultSessionRenderConfig.copy()
        # devSessionRenderConfig.logLevel = 1

        sessionWorker(renderConfig=devSessionRenderConfig,
                      maxLookback=timedelta(days=7, hours=18))
        #print(allStreamersWithVideos)
        # copyWorker()
        # print(getAllStreamingDaysByStreamer()['ChilledChaos'])
        # commandWorker()
        #mainStart()
        allGames = calcGameCounts()
        for game in sorted(allGames.keys(), key=lambda x: (allGames[x], x)):
            print(game, allGames[game])
        del allGames
