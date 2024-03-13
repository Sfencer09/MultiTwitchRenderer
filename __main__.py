#import __init__
from datetime import timedelta
import threading
import os
import sys

if not sys.version_info >= (3, 7, 0):
    raise EnvironmentError(
        "Python version too low, relies on ordered property of dicts")

print(sys.executable)
sys.path.insert(0, os.path.dirname(sys.executable))
#sys.path.append("./MultiTwichRenderer")

if __debug__:
    from config import *
exec(open("config.py").read(), globals())


#import __init__
#from UrwidUI.UrwidMain import urwidUiMain
import UrwidUI.UrwidMain
from RenderConfig import RenderConfig
from CommandWorker import commandWorker
from SharedUtils import calcGameCounts
from SessionWorker import sessionWorker
if COPY_FILES:
    from CopyWorker import copyWorker, copyThread

os.makedirs(logFolder, exist_ok=True)
if COPY_FILES:
    assert localBasepath.strip(' /\\') != basepath.strip(' /\\')

if ENABLE_URWID:
    if COPY_FILES:
        copyThread = threading.Thread(target=copyWorker, kwargs={'copyLog':UrwidUI.UrwidMain.copyText.addLine})
        copyThread.daemon = True
else:
    if COPY_FILES:
        copyThread = threading.Thread(target=copyWorker)
        copyThread.daemon = True

def mainStart():
    if ENABLE_URWID:
        try:
            UrwidUI.UrwidMain.urwidUiMain()
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
        if COPY_FILES:
            copyThread.start()
        sessionThread = threading.Thread(target=sessionWorker, kwargs={'renderConfig': defaultSessionRenderConfig,
                                                                       'maxLookback': timedelta(days=DEFAULT_LOOKBACK_DAYS)})
        sessionThread.daemon = True
        sessionThread.start()
        if ENABLE_URWID:
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
