from datetime import datetime, timedelta, timezone
from functools import partial
import os
import time
from typing import Dict

from SharedUtils import convertToDatetime, getVideoOutputPath

from MTRConfig import getConfig
import scanned

from SourceFile import initialize, saveFiledata, scanFiles
from RenderTask import DEFAULT_PRIORITY, RenderTask, setRenderStatus, getRenderStatus
from RenderConfig import RenderConfig
from RenderWorker import renderQueue
if getConfig('main.copyFiles'):
    from CopyWorker import copyQueue

from MTRLogging import getLogger
from MultiTwitchRenderer import generateTilingCommandMultiSegment
logger = getLogger('SessionWorker')

def scanForExistingVideos() -> None:
    basepath = getConfig('main.basepath')
    outputDirectory = getConfig('main.outputDirectory')
    for file in (f for f in os.listdir(os.path.join(basepath, outputDirectory, "S1")) if f.endswith('.mkv') and not f.endswith('.temp.mkv')):
        fullpath = os.path.join(basepath, outputDirectory, "S1")
        nameparts = file.split(' - ')
        assert len(nameparts) == 3, f"Invalid name parts: {nameparts}"  # and nameparts[0] == outputDirectory
        date = nameparts[1]
        streamerAndExt = nameparts[2]
        parts = streamerAndExt.split('.')
        if any((part == 'temp' for part in parts)):
            continue  # temp file, ignore
        # streamer name will never have a space, so anything can be added between the streamer name and the extension and be ignored
        streamer = parts[0].split(' ')[0]
        logger.info(f"Scanned streamer {streamer} and date {date} from file {file}")
        if streamer in scanned.allStreamersWithVideos:
            setRenderStatus(streamer, date, 'FINISHED')
        else:
            logger.info(f"Streamer {streamer} not known")

    """Days will be sorted with the most recent first
    """
def getAllStreamingDaysByStreamer() -> Dict[str, str]:
    daysByStreamer = {}
    for streamer in sorted(scanned.allFilesByStreamer.keys()):
        days = set()
        for file in scanned.allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            fileStartTimestamp = file.startTimestamp
            for chapter in chapters:
                startTime = datetime.fromtimestamp(
                    fileStartTimestamp+chapter['start_time'], getConfig('main.localTimezone'))
                startDate = datetime.strftime(startTime, "%Y-%m-%d")
                days.add(startDate)
                # endTime = datetime.fromtimestamp(fileStartTimestamp+chapter['end_time'], LOCAL_TIMEZONE)
                # endDate = datetime.strftime(endTime, "%Y-%m-%d")
                # days.add(endDate)
        daysByStreamer[streamer] = list(days)
        daysByStreamer[streamer].sort(reverse=True)
    return daysByStreamer


def sessionWorker(monitorStreamers=getConfig('main.monitorStreamers'),
                  maxLookbackDays: int = getConfig('main.sessionLookbackDays'),
                  dataFilepath=getConfig('main.dataFilepath'),
                  renderConfig=RenderConfig(),
                  sessionLog = None):
    #sessionLog = sessionText.addLine
    #allStreamersWithVideos = SourceFile.allStreamersWithVideos
    #global allFilesByStreamer
    #allFilesByStreamer = SourceFile.allFilesByStreamer
    maxLookback = timedelta(days=maxLookbackDays)
    if len(scanned.allFilesByVideoId) == 0:
        # loadFiledata(dataFilepath)
        initialize()
    scanForExistingVideos()
    changeCount = 0
    prevChangeCount = 0
    COPY_FILES = getConfig('main.copyFiles')
    while True:
        oldFileCount = len(scanned.allFilesByVideoId)
        logger.debug(f"{oldFileCount=}")
        scanFiles()
        newFileCount = len(scanned.allFilesByVideoId)
        logger.debug(f"{newFileCount=}")
        if oldFileCount != newFileCount:
            changeCount += 1
            saveFiledata(dataFilepath)
        latestDownloadTime = max(
            (x.downloadTime for x in scanned.allFilesByVideoId.values()))
        currentTime = datetime.now(timezone.utc)
        if changeCount != prevChangeCount:
            logger.info(f'Current time={str(currentTime)}, latest download time={str(latestDownloadTime)}')
            if sessionLog is not None:
                sessionLog(
                    f'Current time={str(currentTime)}, latest download time={str(latestDownloadTime)}')
        timeSinceLastDownload = currentTime - latestDownloadTime
        #if changeCount != prevChangeCount:
        logger.info(f'Time since last download= {str(timeSinceLastDownload)}')
        if sessionLog is not None:
            sessionLog(
                f'Time since last download= {str(timeSinceLastDownload)}')
        if __debug__ or timeSinceLastDownload > timedelta(hours=getConfig('main.minimumSessionWorkerDelayHours')):
            streamingDays = getAllStreamingDaysByStreamer()
            oldestFirst = getConfig('main.queueOldestFirst')
            for streamer in monitorStreamers:
                allDays = streamingDays[streamer]
                if changeCount != prevChangeCount:
                    logger.info(f'Latest streaming days for {streamer}: {allDays[:25]}')
                    if sessionLog is not None:
                        sessionLog(
                            f'Latest streaming days for {streamer}: {allDays[:25]}')
                # allDays comes sorted with the newest first, but that may not be what we want
                # #sorted(allDays[:streamingDays], reverse=oldestFirst)
                daysQueue = []
                for day in allDays:
                    dt = convertToDatetime(day)
                    if maxLookback is not None and datetime.now() - dt > maxLookback:
                        if changeCount != prevChangeCount:
                            logger.detail("Reached max lookback, stopping")
                            if sessionLog is not None:
                                sessionLog("Reached max lookback, stopping")
                        break
                    status = getRenderStatus(streamer, day)
                    if changeCount != prevChangeCount:
                        logger.detail(f'Status for {day} = {status}')
                        if sessionLog is not None:
                            sessionLog(f'Status for {day} = {status}')
                    if status is None:
                        # new file, build command and add to queue
                        #outPath = getVideoOutputPath(streamer, day)
                        daysQueue.append(day)
                        
                        # break #
                    elif maxLookback is None:
                        if changeCount != prevChangeCount:
                            logger.info("Reached last rendered date for streamer, stopping")
                            if sessionLog is not None:
                                sessionLog(
                                    "Reached last rendered date for streamer, stopping\n")
                        break
                if oldestFirst:
                    daysQueue.reverse()
                for day in daysQueue:
                    command = generateTilingCommandMultiSegment(
                            streamer, day, renderConfig) #, outPath)
                    if command is None:  # command cannot be made, maybe solo stream or only one
                        if changeCount != prevChangeCount:
                            logger.info(f"Skipping render for streamer {streamer} from {day}, no render could be built (possibly solo stream?)")
                            if sessionLog is not None:
                                sessionLog(
                                    f"Skipping render for streamer {streamer} from {day}, no render could be built (possibly solo stream?)")
                        setRenderStatus(streamer, day, "SOLO")
                        continue
                    item = RenderTask(streamer, day, renderConfig) #, outPath)
                    logger.info(f"Adding render for streamer {streamer} from {day}")
                    if sessionLog is not None:
                        sessionLog(
                            f"Adding render for streamer {streamer} from {day}")
                    (copyQueue if COPY_FILES else renderQueue).put(
                        (DEFAULT_PRIORITY, item))
                    setRenderStatus(
                        streamer, day, "COPY_QUEUE" if COPY_FILES else "RENDER_QUEUE")
                    changeCount += 1
        else:
            logger.info("Files are too new, waiting longer...")
            if sessionLog is not None:
                sessionLog("Files are too new, waiting longer...")
        prevChangeCount = changeCount
        if __debug__:
            break
        logger.detail("Reached end of session worker loop, sleeping!")
        time.sleep(60*60)  # *24)
