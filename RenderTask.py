import re
import threading
import pickle
import os

from MTRConfig import getConfig
import scanned

from MTRLogging import getLogger
logger = getLogger('RenderTask')

from RenderConfig import RenderConfig
fileDatePattern:re.Pattern = re.compile(r"\d{4}-\d{2}-\d{2}")

class RenderTask:
    def __init__(self, mainStreamer:str, fileDate:str, renderConfig: RenderConfig, outputPath:str=None):
        if fileDatePattern.fullmatch(fileDate) is None:
            raise ValueError(f"Invalid date format! {fileDate=}")
        self.fileDate = fileDate
        self.mainStreamer = mainStreamer
        self.renderConfig = renderConfig
        self.outputPath = outputPath
        # self.commandArray = commandArray
        # self.outputPath = [command for command in commandArray if 'ffmpeg' in command[0]][-1][-1]
        # allInputFiles = [filepath for command in commandArray for filepath in extractInputFiles(command) if type(filepath)==str and 'anullsrc' not in filepath]
        # print(commandArray)
        # allOutputFiles = set([command[-1] for command in commandArray])
        # self.sourceFiles = [filesBySourceVideoPath[filepath] for filepath in allInputFiles if filepath not in allOutputFiles]
        # self.intermediateFiles = set([command[-1] for command in commandArray[:-1]])

    def __lt__(self, cmp):
        return self.fileDate > cmp.fileDate

    def __gt__(self, cmp):
        return self.fileDate < cmp.fileDate

    def __lte__(self, cmp):
        return self.fileDate >= cmp.fileDate

    def __gte__(self, cmp):
        return self.fileDate <= cmp.fileDate

    def __str__(self):
        return f"{self.mainStreamer} {self.fileDate}"

    def __repr__(self):
        return f"QueueItem(mainStreamer={self.mainStreamer}, fileDate={self.fileDate}, renderConfig={self.renderConfig}, outputPath={self.outputPath})"

statusFilePath = getConfig('main.statusFilePath')
renderStatuses = {}
if os.path.isfile(statusFilePath):
    with open(statusFilePath, 'rb') as statusFile:
        renderStatuses = pickle.load(statusFile)
        delKeys = []
        for key, value in renderStatuses.items():
            if value not in ("FINISHED", "ERRORED"):
                delKeys.append(key)
        for key in delKeys:
            del renderStatuses[key]
# renderStatuses = {}
renderStatusLock = threading.RLock()
localFileReferenceCounts = {}
localFileRefCountLock = threading.RLock()
MAXIMUM_PRIORITY = 9999
DEFAULT_PRIORITY = 1000
MANUAL_PRIORITY = 500

def saveRenderStatuses():
    with renderStatusLock:
        with open(statusFilePath, 'wb') as statusFile:
            pickle.dump(renderStatuses, statusFile)

def incrFileRefCount(filename:str):
    assert filename.startswith(getConfig('main.localBasepath'))
    localFileRefCountLock.acquire()
    ret = 0
    if filename not in localFileReferenceCounts.keys():
        localFileReferenceCounts[filename] = 1
        ret = 1
    else:
        localFileReferenceCounts[filename] += 1
        ret = localFileReferenceCounts[filename]
    localFileRefCountLock.release()
    return ret


def decrFileRefCount(filename:str):
    assert filename.startswith(getConfig('main.localBasepath'))
    localFileRefCountLock.acquire()
    ret = 0
    if filename not in localFileReferenceCounts.keys():
        localFileReferenceCounts[filename] = 1
        ret = 1
    else:
        localFileReferenceCounts[filename] += 1
        ret = localFileReferenceCounts[filename]
    localFileRefCountLock.release()
    return ret


def setRenderStatus(streamer:str, date:str, status:str):
    assert status in ("RENDERING", "RENDER_QUEUE",
                      "COPY_QUEUE", "COPYING", "FINISHED", "ERRORED", "SOLO")
    assert fileDatePattern.fullmatch(date)
    assert streamer in scanned.allStreamersWithVideos
    key = f"{streamer}|{date}"
    with renderStatusLock:
        oldStatus = renderStatuses[key] if key in renderStatuses.keys() else None
        renderStatuses[key] = status
        if status in ("FINISHED", "ERRORED"):
            saveRenderStatuses()
    return oldStatus


def getRenderStatus(streamer:str, date:str):
    # print('grs1', date)
    assert fileDatePattern.fullmatch(date)
    # print('grs2', streamer, scanned.allStreamersWithVideos)
    assert streamer in scanned.allStreamersWithVideos
    key = f"{streamer}|{date}"
    renderStatusLock.acquire()
    status = renderStatuses[key] if key in renderStatuses.keys() else None
    renderStatusLock.release()
    return status


def deleteRenderStatus(streamer:str, date:str, *, lock:bool=True):
    assert fileDatePattern.fullmatch(date)
    assert streamer in scanned.allStreamersWithVideos
    key = f"{streamer}|{date}"
    if lock:
        renderStatusLock.acquire()
    if key in renderStatuses.keys():
        currentStatus = renderStatuses[key]
        if currentStatus in ('RENDER_QUEUE', 'COPY_QUEUE'):
            logger.warning(f"Cannot delete render status, current value is {currentStatus}")
            if lock:
                renderStatusLock.release()
            return False
        del renderStatuses[key]
        if lock:
            renderStatusLock.release()
        return True
    else:
        logger.warning(f"Key {key} not found in render statuses")
        if lock:
            renderStatusLock.release()
        return False

def clearErroredStatuses(streamer:str):
    with renderStatusLock:
        delKeys = []
        for key in renderStatuses.keys():
            if key.split("|")[0] == streamer:
                delKeys.append(key)
        for delKey in delKeys:
            del renderStatuses[delKey]

def getRendersWithStatus(status:str):
    renderStatusLock.acquire()
    selectedRenders = [key.split(
        '|') for key in renderStatuses.keys() if renderStatuses[key] == status]
    renderStatusLock.release()
    return selectedRenders