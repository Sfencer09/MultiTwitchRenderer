import os
import sys
import logging

if __debug__:
    from config import *
exec(open("config.py").read(), globals())

def addLoggingLevelModuleLevel(levelName, levelNum, methodName=None):
    # Copied from https://stackoverflow.com/a/35804945
    if not methodName:
        methodName = levelName.lower()
    if hasattr(logging, levelName):
       raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
       raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
       raise AttributeError('{} already defined in logger class'.format(methodName))
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)
    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)
    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)

    
addLoggingLevelModuleLevel('TRACE', logging.DEBUG - 5)
#addLoggingLevel('NOTIFY', logging.INFO + 5)
addLoggingLevelModuleLevel('DETAIL', logging.INFO - 5)

testLogger = logging.getLogger("test")
testLogger.trace("Trace level added!")
testLogger.detail("Detail level added!")

consoleLogLevel = logging.WARNING
fileLogLevel = logging.DEBUG # TODO: move to config or CLI args
__fileHandler = None

def setUpLogging():
    count = 0
    suffix = ""
    fmt = '%(name)s : %(levelname)s [%(asctime)s] %(message)s'
    datefmt= '%m/%d/%Y %H:%M:%S'
    formatter = logging.Formatter(fmt, datefmt=datefmt)
    os.makedirs(logFolder, exist_ok=True)
    while os.path.isfile(os.path.join(logFolder, f"MultiTwitchRenderer{suffix}.log")) and os.path.getsize(os.path.join(logFolder, f"MultiTwitchRenderer{suffix}.log")) > 0:
        suffix = f"-{count}"
        count += 1
    logFilename = os.path.join(logFolder, f"MultiTwitchRenderer{suffix}.log")
    logging.basicConfig(format = fmt,
                        datefmt = datefmt,
                        encoding = 'utf-8',
                        level = consoleLogLevel)
                        #level = logging.WARNING)
    #console = logging.StreamHandler(sys.stdout)
    #console.setLevel(consoleLogLevel)
    #console.setFormatter(formatter)
    global __fileHandler
    __fileHandler = logging.FileHandler(logFilename, encoding='utf-8')
    __fileHandler.setLevel(fileLogLevel)
    __fileHandler.setFormatter(formatter)
    #logging.getLogger('').addHandler(console)
    #logging.getLogger('').addHandler(fileHandle)

# TODO: set using command line flag rather than hard-coding level
setUpLogging()

def getLogger(name:str):
    logger = logging.getLogger(name)
    if logger.level == logging.NOTSET:
        logger.setLevel(min(consoleLogLevel, fileLogLevel))
        if '.' not in name:
            #logger.addHandler(console)
            logger.addHandler(__fileHandler)
    return logger