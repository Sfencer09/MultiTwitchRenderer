from datetime import datetime, timedelta, timezone
from functools import partial
import os
import time as ttime
from .MultiTwitchRenderer import generateTilingCommandMultiSegment

from SharedUtils import convertToDatetime, getVideoOutputPath


import config

from .SourceFile import allStreamersWithVideos, initialize, saveFiledata, scanFiles, allFilesByStreamer, allFilesByVideoId
from .RenderTask import DEFAULT_PRIORITY, RenderTask, setRenderStatus, getRenderStatus
from .RenderConfig import RenderConfig
from .RenderWorker import renderQueue
from .CopyWorker import copyQueue

def scanForExistingVideos() -> None:
    for file in (f for f in os.listdir(os.path.join(config.basepath, config.outputDirectory, "S1")) if f.endswith('.mkv') and not f.endswith('.temp.mkv')):
        fullpath = os.path.join(config.basepath, config.outputDirectory, "S1")
        nameparts = file.split(' - ')
        assert len(nameparts) == 3  # and nameparts[0] == outputDirectory
        date = nameparts[1]
        streamerAndExt = nameparts[2]
        parts = streamerAndExt.split('.')
        if any((part == 'temp' for part in parts)):
            continue  # temp file, ignore
        # streamer name will never have a space, so anything can be added between the streamer name and the extension and be ignored
        streamer = parts[0].split(' ')[0]
        print(f"Scanned streamer {streamer} and date {date} from file {file}")
        if streamer in allStreamersWithVideos:
            setRenderStatus(streamer, date, 'FINISHED')
        else:
            print(f"Streamer {streamer} not known")


def getAllStreamingDaysByStreamer():
    daysByStreamer = {}
    for streamer in sorted(allFilesByStreamer.keys()):
        days = set()
        for file in allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            fileStartTimestamp = file.startTimestamp
            for chapter in chapters:
                startTime = datetime.fromtimestamp(
                    fileStartTimestamp+chapter['start_time'], config.LOCAL_TIMEZONE)
                startDate = datetime.strftime(startTime, "%Y-%m-%d")
                days.add(startDate)
                # endTime = datetime.fromtimestamp(fileStartTimestamp+chapter['end_time'], LOCAL_TIMEZONE)
                # endDate = datetime.strftime(endTime, "%Y-%m-%d")
                # days.add(endDate)
        daysByStreamer[streamer] = list(days)
        daysByStreamer[streamer].sort(reverse=True)
    return daysByStreamer


def sessionWorker(monitorStreamers=config.DEFAULT_MONITOR_STREAMERS,
                  maxLookback: timedelta = config.DEFAULT_MAX_LOOKBACK,
                  dataFilepath=config.DEFAULT_DATA_FILEPATH,
                  renderConfig=RenderConfig(),
                  sessionLog = partial(print, flush=True)):
    #sessionLog = sessionText.addLine
    #global allFilesByVideoId
    if len(allFilesByVideoId) == 0:
        # loadFiledata(dataFilepath)
        initialize()
    scanForExistingVideos()
    changeCount = 0
    prevChangeCount = 0
    while True:
        oldFileCount = len(allFilesByVideoId)
        scanFiles(renderConfig.logLevel > 0)
        newFileCount = len(allFilesByVideoId)
        if oldFileCount != newFileCount:
            changeCount += 1
            saveFiledata(dataFilepath)
        latestDownloadTime = max(
            (x.downloadTime for x in allFilesByVideoId.values()))
        currentTime = datetime.now(timezone.utc)
        if changeCount != prevChangeCount:
            sessionLog(
                f'Current time={str(currentTime)}, latest download time={str(latestDownloadTime)}')
        timeSinceLastDownload = currentTime - latestDownloadTime
        if changeCount != prevChangeCount:
            sessionLog(
                f'Time since last download= {str(timeSinceLastDownload)}')
        if __debug__ or timeSinceLastDownload > config.minimumSessionWorkerDelay:
            streamingDays = getAllStreamingDaysByStreamer()
            for streamer in monitorStreamers:
                # already sorted with the newest first
                allDays = streamingDays[streamer]
                if changeCount != prevChangeCount:
                    sessionLog(
                        f'Latest streaming days for {streamer}: {allDays[:25]}')
                for day in allDays:
                    dt = convertToDatetime(day)
                    if maxLookback is not None and datetime.now() - dt > maxLookback:
                        if changeCount != prevChangeCount:
                            sessionLog("Reached max lookback, stopping")
                        break
                    status = getRenderStatus(streamer, day)
                    if changeCount != prevChangeCount:
                        sessionLog(f'Status for {day} = {status}')
                    if status is None:
                        # new file, build command and add to queue
                        outPath = getVideoOutputPath(streamer, day)
                        command = generateTilingCommandMultiSegment(
                            streamer, day, renderConfig, outPath)
                        if command is None:  # command cannot be made, maybe solo stream or only one
                            if changeCount != prevChangeCount:
                                sessionLog(
                                    f"Skipping render for streamer {streamer} from {day}, no render could be built (possibly solo stream?)")
                            continue
                        item = RenderTask(streamer, day, renderConfig, outPath)
                        sessionLog(
                            f"Adding render for streamer {streamer} from {day}")
                        (copyQueue if config.COPY_FILES else renderQueue).put(
                            (DEFAULT_PRIORITY, item))
                        setRenderStatus(
                            streamer, day, "COPY_QUEUE" if config.COPY_FILES else "RENDER_QUEUE")
                        changeCount += 1
                        # break #
                    elif maxLookback is None:
                        if changeCount != prevChangeCount:
                            sessionLog(
                                "Reached last rendered date for streamer, stopping\n")
                        break
        else:
            sessionLog("Files are too new, waiting longer...")
        prevChangeCount = changeCount
        # if __debug__:
        #    break
        ttime.sleep(60*60)  # *24)
