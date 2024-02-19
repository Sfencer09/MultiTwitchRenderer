from datetime import datetime, timezone
import os
from typing import List

import config
import scanned

def convertToDatetime(timestamp: int | float | str | datetime):
    if isinstance(timestamp, int) or isinstance(timestamp, float):
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
    elif isinstance(timestamp, str):
        dt = datetime.fromisoformat(timestamp)
    elif isinstance(timestamp, datetime):
        dt = timestamp
    else:
        raise TypeError(
            f"Invalid type '{type(timestamp)}' for timestamp '{str(timestamp)}'")
    return dt


def insertSuffix(outpath:str, suffix:str):
    dotIndex = outpath.rindex('.')
    return outpath[:dotIndex] + suffix + outpath[dotIndex:]


def extractInputFiles(ffmpegCommand: List[str]):
    isInput = False
    files = []
    for st in ffmpegCommand:
        if st == '-i':
            isInput = True
        elif isInput:
            if st != 'anullsrc':
                files.append(st)
            isInput = False
    return files

# def localDateFromTimestamp(timestamp:int|float):
#    dt = datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE)
    # startDate = datetime.strftime(startTime, "%Y-%m-%d")

def getVideoOutputPath(streamer, date):
    return os.path.join(config.basepath, config.outputDirectory, "S1", f"{config.outputDirectory} - {date} - {streamer}.mkv")


def calcGameCounts():
    allGames = {}
    #global allFilesByStreamer
    for streamer in sorted(scanned.allFilesByStreamer.keys()):
        for file in scanned.allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            for chapter in chapters:
                game = chapter['title']
                if game not in allGames.keys():
                    allGames[game] = 1
                else:
                    allGames[game] += 1
    return allGames


def calcGameTimes():
    allGames = {}
    for streamer in sorted(scanned.allFilesByStreamer.keys()):
        for file in scanned.allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            for chapter in chapters:
                game = chapter['title']
                length = chapter['end_time'] - chapter['start_time']
                if game not in allGames.keys():
                    allGames[game] = length
                else:
                    allGames[game] += length
    return allGames
