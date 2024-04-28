import os
import sys
import logging

import MTRArgParse

args = MTRArgParse.getArgs()

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
#addLoggingLevelModuleLevel('NOTIFY', logging.WARNING + 5)
addLoggingLevelModuleLevel('DETAIL', logging.INFO - 5)

testLogger = logging.getLogger("test")
testLogger.trace("Trace level added!")
testLogger.detail("Detail level added!")

_consoleLogLevel = getattr(logging, args.consoleLogLevel.upper())
_fileLogLevel = getattr(logging, args.fileLogLevel.upper())
__fileHandler = None

def setUpLogging():
    count = 0
    suffix = ""
    fmt = '%(name)s : %(levelname)s [%(asctime)s] %(message)s'
    datefmt= '%m/%d/%Y %H:%M:%S'
    logFolder = args.logFolder
    os.makedirs(logFolder, exist_ok=True)
    while os.path.isfile(os.path.join(logFolder, f"MultiTwitchRenderer{suffix}.log")) and os.path.getsize(os.path.join(logFolder, f"MultiTwitchRenderer{suffix}.log")) > 0:
        suffix = f"-{count}"
        count += 1
    logging.basicConfig(filename = os.path.join(logFolder, f"MultiTwitchRenderer{suffix}.log"),
                        format = fmt,
                        datefmt = datefmt,
                        encoding='utf-8',
                        level = min(_consoleLogLevel, _fileLogLevel))
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(_consoleLogLevel)
    formatter = logging.Formatter(fmt, datefmt=datefmt)
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    logging.getLogger('numba').handlers.clear()
    logging.getLogger('numba').setLevel(logging.WARNING)
    logging.getLogger('numba').addHandler(logging.NullHandler())
    logging.getLogger('numba.core').handlers.clear()
    logging.getLogger('numba.core').setLevel(logging.WARNING)
    logging.getLogger('numba.core').addHandler(logging.NullHandler())
    logging.getLogger('numba.core.byteflow').handlers.clear()
    logging.getLogger('numba.core.byteflow').setLevel(logging.WARNING)
    logging.getLogger('numba.core.byteflow').addHandler(logging.NullHandler())

setUpLogging()

def getLogger(name:str):
    logger = logging.getLogger(name)
    return logger