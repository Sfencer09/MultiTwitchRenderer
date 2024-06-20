#import __init__
from datetime import timedelta
import threading
import os
import sys

if not sys.version_info >= (3, 11, 0):
    raise EnvironmentError(
        "Python version too low (<3.11), relies on new iso format parsing in datetime.time")

from MTRLogging import getLogger
import MTRArgParse
logger = getLogger('Main')
logFolder = MTRArgParse.getArgs().logFolder

logger.info(sys.executable)
sys.path.insert(0, os.path.dirname(sys.executable))
#sys.path.append("./MultiTwichRenderer")

import MTRConfig

COPY_FILES = MTRConfig.getConfig('main.copyFiles')
localBasepath = MTRConfig.getConfig('main.localBasepath')
basepath = MTRConfig.getConfig('main.basepath')
ENABLE_URWID = MTRConfig.getConfig('internal.ENABLE_URWID')

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
    logger.info("Copying files is enabled!")

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
                logger.warn(
                    "Unable to start urwid loop, possibly in Jupyter Notebook?\nFalling back to simple terminal control!")
                commandWorker()
            else:
                raise ex
    else:
        commandWorker()




if __name__ == '__main__':
    defaultSessionRenderConfig = RenderConfig()
    
    if not __debug__:
        logger.info("Deployment mode")
        if COPY_FILES:
            copyThread.start()
        sessionThread = threading.Thread(target=sessionWorker, kwargs={'renderConfig': defaultSessionRenderConfig,
                                                                       'maxLookbackDays': MTRConfig.getConfig('main.sessionLookbackDays')})
        sessionThread.daemon = True
        sessionThread.start()
        if ENABLE_URWID:
            mainStart()
        else:
            commandWorker()
        sys.exit(0)
    else:
        logger.info("Development mode")
        devSessionRenderConfig = defaultSessionRenderConfig.copy()
        # devSessionRenderConfig.logLevel = 1

        sessionWorker(renderConfig=devSessionRenderConfig,
                      maxLookbackDays=14)
        #logging.detail(allStreamersWithVideos)
        # copyWorker()
        # logging.detail(getAllStreamingDaysByStreamer()['ChilledChaos'])
        commandWorker()
        #mainStart()
        allGames = calcGameCounts()
        for game in sorted(allGames.keys(), key=lambda x: (allGames[x], x)):
            logger.detail(game, allGames[game])
        del allGames
