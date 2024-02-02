# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import urwid  # , os, threading, functools
import os
import subprocess
import json
import time
import math
import pickle
import re
import queue
import threading
import shutil
import random
import sys
import signal
import gc
from datetime import datetime, timezone, time, timedelta
from schema import Schema, Or, And, Optional, Use
from fuzzysearch import find_near_matches
from thefuzz import process as fuzzproc
from functools import reduce, partial
from pprint import pprint
from shlex import quote
import time as ttime

print = partial(print, flush=True)

if not sys.version_info >= (3, 7, 0):
    raise EnvironmentError(
        "Python version too low, relies on ordered property of dicts")

configPath = './Documents/MultiTwitchRenderer/config.py' if __debug__ else './config.py'
HW_DECODE = 1
HW_INPUT_SCALE = 2
HW_OUTPUT_SCALE = 4
HW_ENCODE = 8

with open(configPath) as configFile:
    exec(configFile.read())


def getVideoInfo(videoFile: str):
    probeResult = subprocess.run(['ffprobe', '-v', 'quiet',
                                  '-print_format', 'json=c=1',
                                  '-show_format', '-show_streams',
                                  videoFile], capture_output=True)
    # print(probeResult)
    if probeResult.returncode != 0:
        return None
    info = json.loads(probeResult.stdout.decode())
    return info


class SourceFile:
    def __init__(self, streamer, videoId, *, videoFile=None, infoFile=None, chatFile=None):
        assert videoFile is None or os.path.isabs(videoFile)
        assert infoFile is None or os.path.isabs(infoFile)
        self.streamer = streamer
        self.videoId = videoId
        self.videoFile = None
        if videoFile is not None:
            self.setVideoFile(videoFile)
        self.localVideoFile = None
        self.videoInfo = None
        self.infoFile = None
        if infoFile is not None:
            self.setInfoFile(infoFile)
        self.chatFile = None
        self.parsedChat = None
        if chatFile is not None:
            self.setChatFile(chatFile)

    def __repr__(self):
        return f"SourceFile(streamer=\"{self.streamer}\", videoId=\"{self.videoId}\", videoFile=\"{self.videoFile}\", infoFile=\"{self.infoFile}\", chatFile=\"{self.chatFile}\")"

    def isComplete(self):
        return self.videoFile is not None and self.infoFile is not None

    def setInfoFile(self, infoFile):
        if self.infoFile == infoFile:
            return
        assert self.infoFile is None, f"Cannot overwrite existing info file {self.chatFile} with new file {infoFile}"
        assert infoFile.endswith(infoExt) and os.path.isfile(
            infoFile) and os.path.isabs(infoFile)
        self.infoFile = infoFile
        with open(infoFile) as file:
            self.infoJson = trimInfoDict(json.load(file))
        self.duration = self.infoJson['duration']
        self.startTimestamp = self.infoJson['timestamp']
        self.endTimestamp = self.duration + self.startTimestamp

    def setVideoFile(self, videoFile):
        if self.videoFile == videoFile:
            return
        assert self.videoFile is None, f"Cannot overwrite existing video file {self.chatFile} with new file {videoFile}"
        assert any((videoFile.endswith(videoExt) for videoExt in videoExts)
                   ) and os.path.isfile(videoFile) and os.path.isabs(videoFile)
        self.videoFile = videoFile
        self.downloadTime = convertToDatetime(os.path.getmtime(videoFile))

    def setChatFile(self, chatFile):
        if self.chatFile == chatFile:
            return
        assert self.chatFile is None, f"Cannot overwrite existing chat file {self.chatFile} with new file {chatFile}"
        assert chatFile.endswith(chatExt) and os.path.isfile(
            chatFile) and os.path.isabs(chatFile)
        self.chatFile = chatFile
        if self.streamer in streamersParseChatList:
            self.parsedChat = ParsedChat(self, chatFile)

    def getVideoFileInfo(self):
        if self.videoInfo is None:
            self.videoInfo = getVideoInfo(
                self.videoFile if self.localVideoFile is None else self.localVideoFile)
        return self.videoInfo


class ParsedChat:
    def __init__(self, parentFile: SourceFile, chatFile: str):
        self.parentFile = parentFile
        with open(chatFile) as chatFileContents:
            chatJson = json.load(chatFileContents)
        # print(chatFile)
        nightbotGroupComments = []
        groupEditComments = []
        groups = []
        lastCommandComment = None
        # self.chatJson = chatJson
        # print(f"Parsed {len(chatJson)} comments")
        for comment in chatJson:
            commenter = comment['commenter']
            user = commenter['displayName'] if commenter is not None else None
            messageFragments = comment['message']['fragments']
            if len(messageFragments) == 0:
                continue
            firstMessageFrag = messageFragments[0]['text']
            fullMessage = " ".join((frag['text'] for frag in messageFragments))
            offset = comment['contentOffsetSeconds']
            timestamp = comment['createdAt']
            if user == 'Nightbot':
                if lastCommandComment is not None and offset - lastCommandComment['contentOffsetSeconds'] < 4:
                    nightbotGroupComments.append(comment)
                    group = parsePlayersFromGroupMessage(fullMessage)
                    # print(fullMessage)
                    # print(group)
                    if self.parentFile.streamer in group:
                        group.remove(self.parentFile.streamer)
                    convertedTime = datetime.fromisoformat(timestamp)
                    # if len(groups) == 0 or set(group) != set(groups[-1].group):
                    groups.append({'group': group, 'time': convertedTime})
                lastCommandComment = None
            else:
                if firstMessageFrag.lower().strip() in ('!who', '!group'):
                    lastCommandComment = comment
                else:
                    sub = re.sub(r'\s+', ' ', fullMessage.lower())
                    if (any((badge['setID'] == 'moderator' for badge in comment['message']['userBadges'])) and
                            (sub.startswith('!editcom !group') or sub.startswith('!commands edit !group'))):
                        groupEditComments.append(comment)
                        newCommandText = fullMessage[6 +
                                                     fullMessage.lower().index('!group'):]
                        group = parsePlayersFromGroupMessage(newCommandText)
                        if self.parentFile.streamer in group:
                            group.remove(self.parentFile.streamer)
                        # print(fullMessage)
                        # print(newCommandText)
                        # print(sorted(group), end='\n\n')
                        convertedTime = datetime.fromisoformat(timestamp)
                        groups.append({'group': group, 'time': convertedTime})
        self.nightbotGroupComments = nightbotGroupComments
        self.groupEditComments = groupEditComments
        self.groups = groups

    def getGroupAtTimestamp(self, timestamp: int | float | str | datetime):
        dt = convertToDatetime(timestamp)
        lastMatch = []
        for group in self.groups:
            if group.time < dt:
                lastMatch = group.group
            else:
                break
        return lastMatch

    def getAllPlayersOverRange(self, startTimestamp: int | float | str | datetime, endTimestamp: int | float | str | datetime):
        start = convertToDatetime(startTimestamp)
        end = convertToDatetime(endTimestamp)
        allPlayers = set()
        lastMatch = []
        for group in self.groups:
            if len(lastMatch) == 0 and group['time'] < start:
                # get last group before this range, in case no commands are found
                lastMatch = group['group']
            if start < group['time'] < end:
                allPlayers.update(group['group'])  # command is within range,
        return allPlayers if len(allPlayers) > 0 else lastMatch


class Session:
    def __init__(self, file: SourceFile, game: str, startTimestamp: int | float, endTimestamp: int | float):
        self.startTimestamp = startTimestamp
        self.endTimestamp = endTimestamp
        self.file = file
        self.game = game

    def hasOverlap(self: SourceFile, cmp: SourceFile, useChat=True, targetRange=None):
        if self.startTimestamp > cmp.endTimestamp or self.endTimestamp < cmp.startTimestamp:
            return False
        if targetRange is None:
            if useChat:
                if self.file.parsedChat is not None:
                    selfPlayers = self.file.parsedChat.getAllPlayersOverRange(
                        self.startTimestamp-15, self.endTimestamp)
                    if cmp.file.streamer in selfPlayers:
                        return True
                if cmp.file.parsedChat is not None:
                    cmpPlayers = cmp.file.parsedChat.getAllPlayersOverRange(
                        cmp.startTimestamp-15, self.endTimestamp)
                    if self.file.streamer in cmpPlayers:
                        return True
            return self.game == cmp.game and (not useChat or (self.file.parsedChat is None and cmp.file.parsedChat is None))
        else:
            rangeStart, rangeEnd = targetRange
            if self.endTimestamp < rangeStart or cmp.endTimestamp < rangeStart or self.startTimestamp > rangeEnd or cmp.startTimestamp > rangeEnd:
                return False
            overlapStart = max(self.startTimestamp,
                               cmp.startTimestamp, rangeStart)
            overlapEnd = min(self.endTimestamp, cmp.endTimestamp, rangeEnd)
            overlapLength = overlapEnd - overlapStart
            # if overlapLength < (rangeEnd - rangeStart) / 2:
            #    return False
            if useChat:
                if self.file.parsedChat is not None:
                    selfPlayers = self.file.parsedChat.getAllPlayersOverRange(
                        overlapStart, overlapEnd)
                    if cmp.file.streamer in selfPlayers:
                        return True
                if cmp.file.parsedChat is not None:
                    cmpPlayers = cmp.file.parsedChat.getAllPlayersOverRange(
                        overlapStart, overlapEnd)
                    if self.file.streamer in cmpPlayers:
                        return True
            return self.game == cmp.game and (not useChat or (self.file.parsedChat is None and cmp.file.parsedChat is None))
            # raise Exception("Not implemented yet")

    def __repr__(self):
        return f"Session(game=\"{self.game}\", startTimestamp={self.startTimestamp}, endTimestamp={self.endTimestamp}, file=\"{self.file}\")"


print("Starting")


# %%
def calcTileWidth(numTiles):
    return int(math.sqrt(numTiles-1.0))+1


def trimInfoDict(infoDict: dict):
    newDict = dict(infoDict)
    del newDict['thumbnails']
    del newDict['formats']
    del newDict['subtitles']
    del newDict['http_headers']
    return newDict


def getHasHardwareAceleration():
    SCALING = HW_INPUT_SCALE | HW_OUTPUT_SCALE
    process1 = subprocess.run(
        [f"{ffmpegPath}ffmpeg", "-version"], capture_output=True)
    print(process1.stdout.decode())
    try:
        process2 = subprocess.run(
            ["nvidia-smi", "-q", "-d", "MEMORY,UTILIZATION"], capture_output=True)
        nvidiaSmiOutput = process2.stdout.decode()
        print(nvidiaSmiOutput)
        print(process2.returncode)
        if process2.returncode == 0:
            encoding = False
            decoding = False
            rowCount = 0
            for row in nvidiaSmiOutput.split('\n'):
                if 'Encoder' in row:
                    encoding = 'N/A' not in row
                elif 'Decoder' in row:
                    decoding = 'N/A' not in row
                rowCount += 1
            print(f"Row count: {rowCount}")
            mask = SCALING
            if decoding:
                mask |= HW_DECODE
            if encoding:
                mask |= HW_ENCODE
            return ('NVIDIA', mask)
    except Exception as ex:
        print(ex)
    try:
        process3 = subprocess.run(["rocm-smi", "--json"], capture_output=True)
        amdSmiOutput = process3.stdout.decode()
        print(amdSmiOutput)
        print(process3.returncode)
        if process3.returncode == 0:
            print("Parsing AMD HW acceleration from rocm-smi not implemented yet, assuming all functions available")
            return ('AMD', HW_DECODE | HW_ENCODE)
    except Exception as ex:
        print(ex)
    return (None, 0)


HWACCEL_BRAND, HWACCEL_FUNCTIONS = getHasHardwareAceleration()
if HWACCEL_BRAND is not None:
    print(f'{HWACCEL_BRAND} hardware video acceleration detected')
    print(f'Functions:')
    if HWACCEL_FUNCTIONS & HW_DECODE != 0:
        print("    Decode")
    if HWACCEL_FUNCTIONS & (HW_INPUT_SCALE | HW_OUTPUT_SCALE) != 0:
        print("    Scaling")
    if HWACCEL_FUNCTIONS & HW_ENCODE != 0:
        print("    Encode")
else:
    print('No hardware video decoding detected!')


# inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
# inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
# if useHardwareAcceleration&HW_INPUT_SCALE != 0 and cutMode == 'trim':
#    inputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
# HWACCEL_BRAND
HWACCEL_VALUES = {
    'NVIDIA': {
        # 'support_mask': HW_DECODE|HW_INPUT_SCALE|HW_OUTPUT_SCALE|HW_ENCODE,
        'scale_filter': '_npp',
        'pad_filter': '_opencl',
        'upload_filter': '_cuda',
        'decode_input_options': ('-threads', '1', '-c:v', 'h264_cuvid'),
        'scale_input_options': ('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'),
        'encode_codecs': ('h264_nvenc', 'hevc_nvenc'),
    },
    'AMD': {
        # 'support_mask': HW_DECODE|HW_ENCODE,
        'scale_filter': None,
        'pad_filter': None,
        'upload_filter': '',
        # ('-hwaccel', 'dxva2'), #for AV1 inputs only: ('-extra_hw_frames', '10'),
        'decode_input_options': ('-hwaccel', 'd3d11va'),
        'scale_input_options': None,
        'encode_codecs': ('h264_amf', 'hevc_amf'),
    },
    'Intel': {
        # 'support_mask': HW_DECODE|HW_ENCODE,
        'scale_filter': None,
        'pad_filter': None,
        'upload_filter': '',
        'decode_input_options': ('-hwaccel', 'qsv', '-c:v', 'h264_qsv'),
        'scale_input_options': None,
        'encode_codecs': ('h264_qsv', 'hevc_qsv'),
    },
}
if HWACCEL_BRAND is not None:
    ACTIVE_HWACCEL_VALUES = HWACCEL_VALUES[HWACCEL_BRAND]
else:
    ACTIVE_HWACCEL_VALUES = None

# def localDateFromTimestamp(timestamp:int|float):
#    dt = datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE)
    # startDate = datetime.strftime(startTime, "%Y-%m-%d")

# tileResolutions = [None,"1920:1080", "1920:1080", "1280:720", "960:540", "768:432", "640:360", "640:360"]
# outputResolutions = [None, "1920:1080", "3840:1080", "3840:2160", "3840:2160", "3840:2160", "3840:2160", "4480:2520"]


def parsePlayersFromGroupMessage(message: str):
    players = []
    messageLowercase = message.lower()
    for streamer in globalAllStreamers:
        fuzzymatches = find_near_matches(
            streamer.lower(), messageLowercase, max_l_dist=len(streamer)//5)
        if len(fuzzymatches) > 0:
            players.append(streamer)
        elif streamer in streamerAliases.keys():
            for alias in streamerAliases[streamer]:
                fuzzymatches = find_near_matches(
                    alias.lower(), messageLowercase, max_l_dist=len(alias)//5)
                if len(fuzzymatches) > 0:
                    players.append(streamer)
                    break
    return players


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

# print(parsePlayersFromGroupMessage('Chilled is playing with Junkyard129, Kruzadar, KYR_SP33DY, LarryFishburger, and YourNarrator!'))


# 0: Build filesets for lookup and looping; pair video files with their info files (and chat files if present)
if 'allFilesByVideoId' not in globals():
    print('Creating data structures')
    allFilesByVideoId = {}  # string:SourceFile
    allFilesByStreamer = {}  # string:[SourceFile]
    allStreamersWithVideos = []
    allStreamerSessions = {}
    allScannedFiles = set()
    filesBySourceVideoPath = {}


def scanSessionsFromFile(file: SourceFile):
    streamer = file.streamer
    if streamer not in allStreamerSessions.keys():
        allStreamerSessions[streamer] = []
    chapters = file.infoJson['chapters']
    startTime = file.startTimestamp
    for chapter in chapters:
        game = chapter['title']
        chapterStart = startTime + chapter['start_time']
        chapterEnd = startTime + chapter['end_time']
        session = Session(file, game, chapterStart, chapterEnd)
        allStreamerSessions[streamer].append(session)


def scanFiles(log=False):
    # newFiles = set()
    # newFilesByStreamer = dict()
    newFilesByVideoId = dict()
    for streamer in globalAllStreamers:
        if log:
            print(f"Scanning streamer {streamer} ", end='')
        newStreamerFiles = []
        streamerBasePath = os.path.join(basepath, streamer, 'S1')
        count = 0
        for filename in (x for x in os.listdir(streamerBasePath) if any((x.endswith(ext) for ext in (videoExts + [infoExt, chatExt])))):
            filepath = os.path.join(streamerBasePath, filename)
            if filepath in allScannedFiles:
                continue
            filenameSegments = re.split(videoIdRegex, filename)
            # print(filenameSegments)
            if len(filenameSegments) < 3:
                continue
            assert len(filenameSegments) >= 3
            videoId = filenameSegments[-2]
            # print(videoId, filepath, sep=' '*8)
            if log and count % 10 == 0:
                print('.', end='')
            file = None
            if videoId not in allFilesByVideoId.keys() and videoId not in newFilesByVideoId.keys():
                if any((filename.endswith(videoExt) for videoExt in videoExts)):
                    file = SourceFile(streamer, videoId, videoFile=filepath)
                    # filesBySourceVideoPath[filepath] = file
                elif filename.endswith(infoExt):
                    file = SourceFile(streamer, videoId, infoFile=filepath)
                else:
                    assert filename.endswith(chatExt)
                    file = SourceFile(streamer, videoId, chatFile=filepath)
                # allFilesByVideoId[videoId] = file
                newFilesByVideoId[videoId] = file
                newStreamerFiles.append(file)
            else:
                file = allFilesByVideoId[videoId] if videoId in allFilesByVideoId.keys(
                ) else newFilesByVideoId[videoId]
                if any((filename.endswith(videoExt) for videoExt in videoExts)):
                    file.setVideoFile(filepath)
                    # filesBySourceVideoPath[filepath] = file
                elif filename.endswith(infoExt):
                    file.setInfoFile(filepath)
                else:
                    assert filename.endswith(chatExt)
                    file.setChatFile(filepath)
                    # if streamer in streamersParseChatList:
                    #    file.parsedChat = ParsedChat(filepath)
                # if file.isComplete():
                #    newFiles.add(file)
            # allScannedFiles.add(filepath)
            count += 1
        count = 0
        if log:
            print()
            # print('*', end='')
        newCompleteFiles = []
        for i in reversed(range(len(newStreamerFiles))):
            file = newStreamerFiles[i]
            if file.isComplete():
                allScannedFiles.add(file.videoFile)
                allScannedFiles.add(file.infoFile)
                if file.chatFile is not None:
                    allScannedFiles.add(file.chatFile)
                filesBySourceVideoPath[file.videoFile] = file
                allFilesByVideoId[file.videoId] = file
                count += 1
                scanSessionsFromFile(file)
                newCompleteFiles.append(file)
                # if file.chatFile is not None and streamer in streamersParseChatList:
                # if file.parsedChat is None:
                #    file.parsedChat = ParsedChat(file.chatFile)
                #    if log and count % 10 == 0:
                #        print('.', end='')
                #    count += 1
                # else:
                #    file.parsedChat = None
                # filesBySourceVideoPath[file.videoPath] = file
            # else:
                # print(f"Deleting incomplete file at index {i}: {streamerFiles[i]}")
            #    if file.videoFile is not None:
            #        del filesBySourceVideoPath[file.videoFile]
            #    del allFilesByVideoId[file.videoId]
            #    del streamerFiles[i]
        # if log:
        if count > 0 or log:
            print(f"Scanned streamer {streamer} with {count} files")
        if len(newStreamerFiles) > 0:
            if streamer not in allFilesByStreamer.keys():
                # allStreamersWithVideos.append(streamer)
                allFilesByStreamer[streamer] = newCompleteFiles
            else:  # streamer already had videos scanned in
                allFilesByStreamer[streamer].extend(newCompleteFiles)
    global allStreamersWithVideos
    allStreamersWithVideos = list(allFilesByStreamer.keys())
    if log:
        print("Step 0: ", allStreamersWithVideos, end="\n\n\n")

    # [OLD]       1. Build sorted (by start time) array of sessions by streamer
    # for streamer in allStreamersWithVideos:
    #    allStreamerSessions[streamer] = []
    #    for file in allFilesByStreamer[streamer]:
    # 1. Add new sessions for each streamer

    for sessionList in allStreamerSessions.values():
        sessionList.sort(key=lambda x: x.startTimestamp)
    # for streamer in allStreamersWithVideos:
    #    allStreamerSessions[streamer].sort(key=lambda x:x.startTimestamp)
    if log:
        print("Step 1: ", sum((len(x)
              for x in allStreamerSessions.values())), end="\n\n\n")

# class SourceFile:
#    SourceFile(self, streamer, videoId, *, videoFile=None, infoFile=None, chatFile=None)
#    streamer:str
#    videoId:str
#    videoFile:str
#    infoFile:str
#    infoJson:dict
#    startTimestamp:int|float
#    endTimestamp:int|float
#    chatFile?:str
#    parsedChat:ParsedChat
# class ParsedChat:
#    self.nightbotGroupComments:
#    self.groupEditComments = groupEditComments
#    self.groups = groups
#    getGroup(self, timestamp:int|float)
# class Session:
#    def __init__(self, file:SourceFile, game:str, startTimestamp:int, endTimestamp:int)
#    file:SourceFile
#    game:str
#    startTimestamp:int
#    endTimestamp:int
#    hasOverlap(self, cmp:Session, useChat:bool=True):bool
# allFilesByVideoId:{str:SourceFile}
# allFilesByStreamer:{str:SourceFile[]}
# allStreamersWithVideos:str[]
# characterReplacements:{str:str}
# def calcTileWidth(numTiles:int):int
# tileResolutions:str[]
# outputResolutions:str[]


def getVideoOutputPath(streamer, date):
    return os.path.join(basepath, outputDirectory, "S1", f"{outputDirectory} - {date} - {streamer}.mkv")


def insertSuffix(outpath, suffix):
    dotIndex = outpath.rindex('.')
    return outpath[:dotIndex]+suffix+outpath[dotIndex:]


def calcResolutions(numTiles, maxNumTiles):
    tileWidth = calcTileWidth(numTiles)
    maxTileWidth = calcTileWidth(maxNumTiles)
    maxOutputResolution = outputResolutions[maxTileWidth]
    scaleFactor = min(
        maxOutputResolution[0] // (16*tileWidth), maxOutputResolution[1] // (9*tileWidth))
    tileX = scaleFactor * 16
    tileY = scaleFactor * 9
    outputX = tileX * tileWidth
    outputY = tileY * tileWidth
    return (f"{tileX}:{tileY}", f"{outputX}:{outputY}")


def generateLayout(numTiles):
    tileWidth = calcTileWidth(numTiles)

    def generateLE(tileNum):  # generateLayoutElement
        x = tileNum % tileWidth
        y = tileNum // tileWidth

        def generateLEC(coord, letter):  # generateLayoutElementComponent
            if coord == 0:
                return "0"
            return "+".join([f"{letter}{n}" for n in range(coord)])
        return f"{generateLEC(x,'w')}_{generateLEC(y,'h')}"
    return "|".join([generateLE(n) for n in range(numTiles)])


def toFfmpegTimestamp(ts: int | float):
    return f"{int(ts)//3600:02d}:{(int(ts)//60)%60:02d}:{float(ts%60):02f}"


trueStrings = ('t', 'y', 'true', 'yes')

defaultRenderConfig = RENDER_CONFIG_DEFAULTS
try:
    with open('./renderConfig.json') as renderConfigJsonFile:
        defaultRenderConfig = json.load(renderConfigJsonFile)
except:
    print("Coult not load renderConfig.json, using defaults from config.py")

acceptedOutputCodecs = ['libx264', 'libx265']
if ACTIVE_HWACCEL_VALUES is not None:
    hardwareOutputCodecs = ACTIVE_HWACCEL_VALUES['encode_codecs']
    acceptedOutputCodecs.extend(hardwareOutputCodecs)
else:
    hardwareOutputCodecs = []

renderConfigSchema = Schema({
    Optional('drawLabels', default=defaultRenderConfig['drawLabels']):
    Or(bool, Use(lambda x: x.lower() in trueStrings)),
    Optional('startTimeMode', default=defaultRenderConfig['startTimeMode']):
    lambda x: x in ('mainSessionStart', 'allOverlapStart'),
    Optional('endTimeMode', default=defaultRenderConfig['endTimeMode']):
    lambda x: x in ('mainSessionEnd', 'allOverlapEnd'),
    Optional('logLevel', default=defaultRenderConfig['logLevel']):
    And(Use(int), lambda x: 0 <= x <= 4),  # max logLevel = 4
    Optional('sessionTrimLookback', default=defaultRenderConfig['sessionTrimLookback']):
    # TODO: convert from number of segments to number of seconds. Same for lookahead
    Use(int),
    Optional('sessionTrimLookahead', default=defaultRenderConfig['sessionTrimLookahead']):
    And(Use(int), lambda x: x >= 0),
    Optional('sessionTrimLookbackSeconds', default=defaultRenderConfig['sessionTrimLookbackSeconds']):
    And(Use(int), lambda x: x >= 0),  # Not implemented yet
    Optional('sessionTrimLookaheadSeconds', default=defaultRenderConfig['sessionTrimLookaheadSeconds']):
    And(Use(int), lambda x: x >= 0),
    # Optional(Or(Optional('sessionTrimLookback', default=0),
    # Optional('sessionTrimLookbackSeconds', default=0), only_one=True), ''): And(int, lambda x: x>=-1),
    # Optional(Or(Optional('sessionTrimLookahead', default=0),
    # Optional('sessionTrimLookaheadSeconds', default=600), only_one=True): And(int, lambda x: x>=0),
    Optional('minGapSize', default=defaultRenderConfig['minGapSize']):
    And(Use(int), lambda x: x >= 0),
    Optional('outputCodec', default=defaultRenderConfig['outputCodec']):
    lambda x: x in acceptedOutputCodecs,
    Optional('encodingSpeedPreset', default=defaultRenderConfig['encodingSpeedPreset']):
    lambda x: x in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium',
                    'slow', 'slower', 'veryslow') or x in [f'p{i}' for i in range(1, 8)],
    Optional('useHardwareAcceleration', default=defaultRenderConfig['useHardwareAcceleration']):
    And(Use(int), lambda x: x & HWACCEL_FUNCTIONS == x),
    # And(Use(int), lambda x: 0 <= x < 16), #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale input, bit 3(4)=scale output, bit 4(8)=encode
    Optional('maxHwaccelFiles', default=defaultRenderConfig['maxHwaccelFiles']):
    And(Use(int), lambda x: x >= 0),
    Optional('minimumTimeInVideo', default=defaultRenderConfig['minimumTimeInVideo']):
    And(Use(int), lambda x: x >= 0),
    Optional('cutMode', default=defaultRenderConfig['cutMode']):
    lambda x: x in ('chunked', ),  # 'trim', 'segment'),
    Optional('useChat', default=defaultRenderConfig['useChat']):
    Or(bool, Use(lambda x: x.lower() in trueStrings)),
    # overrides chat, but will not prevent game matching
    Optional('includeStreamers', default=None):
    # Cannot be passed as string
    Or(lambda x: x is None, [str], {str: Or(lambda x: x is None, [str])}),
    Optional('excludeStreamers', default=None):
    # Cannot be passed as string
    Or(lambda x: x is None, [str], {str: Or(lambda x: x is None, [str])}),
})


class RenderConfig:
    def __init__(self, **kwargs):
        values = renderConfigSchema.validate(kwargs)
        if values['outputCodec'] in hardwareOutputCodecs:
            if values['useHardwareAcceleration'] & HW_ENCODE == 0:
                raise Exception(
                    f"Must enable hardware encoding bit in useHardwareAcceleration if using hardware-accelerated output codec {values['outputCodec']}")
            if values['encodingSpeedPreset'] not in [f'p{i}' for i in range(1, 8)]:
                raise Exception("Must use p1-p7 presets with hardware codecs")
        elif values['encodingSpeedPreset'] not in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'):
            raise Exception("Can only use p1-p7 presets with hardware codecs")
        if values['useHardwareAcceleration'] & HW_OUTPUT_SCALE != 0:
            if values['useHardwareAcceleration'] & HW_ENCODE == 0:
                raise Exception(
                    f"Hardware-accelerated output scaling must currently be used with hardware encoding")
        if values['useHardwareAcceleration'] & HW_ENCODE != 0:
            if values['outputCodec'] not in hardwareOutputCodecs:
                raise Exception(
                    f"Must specify hardware-accelerated output codec if hardware encoding bit in useHardwareAcceleration is enabled")
        for key, value in values.items():
            setattr(self, key, value)

    def copy(self):
        return RenderConfig(**self.__dict__)

    def __repr__(self):
        return f"RenderConfig({', '.join(('='.join((key, str(value))) for key, value in self.__dict__.items()))})"


def generateTilingCommandMultiSegment(mainStreamer, targetDate, renderConfig=RenderConfig(), outputFile=None):
    otherStreamers = [
        name for name in allStreamersWithVideos if name != mainStreamer]
    if outputFile is None:
        outputFile = getVideoOutputPath(mainStreamer, targetDate)
    #########
    drawLabels = renderConfig.drawLabels
    startTimeMode = renderConfig.startTimeMode
    endTimeMode = renderConfig.endTimeMode
    logLevel = renderConfig.logLevel
    sessionTrimLookback = renderConfig.sessionTrimLookback
    sessionTrimLookahead = renderConfig.sessionTrimLookahead
    sessionTrimLookbackSeconds = renderConfig.sessionTrimLookbackSeconds
    sessionTrimLookaheadSeconds = renderConfig.sessionTrimLookaheadSeconds
    minGapSize = renderConfig.minGapSize
    outputCodec = renderConfig.outputCodec
    encodingSpeedPreset = renderConfig.encodingSpeedPreset
    useHardwareAcceleration = renderConfig.useHardwareAcceleration
    maxHwaccelFiles = renderConfig.maxHwaccelFiles
    minimumTimeInVideo = renderConfig.minimumTimeInVideo
    cutMode = renderConfig.cutMode
    useChat = renderConfig.useChat
    excludeStreamers = renderConfig.excludeStreamers
    # includeStreamers = renderConfig.includeStreamers
    #########
    # 2. For a given day, target a streamer and find the start and end times of their sessions for the day
    targetDateStartTime = datetime.combine(
        datetime.fromisoformat(targetDate), DAY_START_TIME)
    targetDateEndTime = targetDateStartTime + timedelta(days=1)
    if logLevel >= 1:
        print(targetDate, targetDateStartTime, targetDateEndTime)
        print('other streamers', otherStreamers)
    mainSessionsOnTargetDate = list(filter(lambda x: targetDateStartTime <= datetime.fromtimestamp(
        x.startTimestamp, tz=UTC_TIMEZONE) <= targetDateEndTime, allStreamerSessions[mainStreamer]))
    if len(mainSessionsOnTargetDate) == 0:
        raise ValueError(
            "Selected streamer does not have any sessions on the target date")
    mainSessionsOnTargetDate.sort(key=lambda x: x.startTimestamp)
    if logLevel >= 1:
        print("\n\n\nStep 2: ", targetDateStartTime, targetDateEndTime)
        if logLevel >= 2:
            pprint(mainSessionsOnTargetDate)

    groupsFromMainFiles = reduce(list.append,  # list.__add__,
                                 (file.parsedChat.groups for file in set((session.file for session in mainSessionsOnTargetDate)
                                                                         ) if file.parsedChat is not None), [])
    if logLevel >= 1:
        print("\n\nStep 2.1: ")
        pprint(groupsFromMainFiles)

        mainFiles = set((session.file for session in mainSessionsOnTargetDate))
        for mainFile in mainFiles:
            print(mainFile.infoFile)
            chat = mainFile.parsedChat
            if chat is not None:
                pprint(chat.groups)

    # 3. For all other streamers, build a sorted array of sessions that have matching games & have time overlap (and/or
        # appear in a !who-type command during that time if rechat is found)
    secondarySessionsArray = []
    inputSessionsByStreamer = {}
    inputSessionsByStreamer[mainStreamer] = mainSessionsOnTargetDate
    for streamer in allStreamerSessions.keys():
        if streamer == mainStreamer:
            continue
        inputSessionsByStreamer[streamer] = []
        for session in allStreamerSessions[streamer]:
            if any((session.hasOverlap(x, useChat) for x in mainSessionsOnTargetDate)):
                if excludeStreamers is not None and streamer in excludeStreamers.keys():
                    if excludeStreamers[streamer] is None or session.game in excludeStreamers[streamer]:
                        continue
                secondarySessionsArray.append(session)
                inputSessionsByStreamer[streamer].append(session)
        inputSessionsByStreamer[streamer].sort(key=lambda x: x.startTimestamp)
    if logLevel >= 3:
        print("\n\n\nStep 3: ")  # , secondarySessionsArray)
        pprint(inputSessionsByStreamer)

    # 4. Build a separate array of all sessions from #3, sorted by start time
    secondarySessionsArray.sort(key=lambda x: x.startTimestamp)
    if logLevel >= 3:
        print("\n\n\nStep 4: ")
        pprint(secondarySessionsArray)

    # 5. Build array of streamers that have sessions in #4, with the target streamer first and the others sorted by
        # first start time - these will become the audio output stream orders
    allInputStreamers = [mainStreamer]
    allInputStreamersSortKey = {}
    allInputStreamersSortKey[mainStreamer] = 0
    for session in secondarySessionsArray:
        streamer = session.file.streamer
        if streamer not in allInputStreamers:
            allInputStreamersSortKey[streamer] = len(allInputStreamers)
            allInputStreamers.append(streamer)
    allInputStreamers.sort(key=lambda x: allInputStreamersSortKey[x])
    secondaryStreamers = [x for x in allInputStreamers if x != mainStreamer]
    if logLevel >= 1:
        print("\n\n\nStep 5: ", allInputStreamers, secondaryStreamers)
    if len(allInputStreamers) == 1:
        if logLevel >= 1:
            print("Only one streamer found, nothing to render!")
        return None

    # 6. For each streamer in #5, build an array of pairs of start & end timestamps for sessions from #3 while
        # combining those that connect
    inputSessionTimestampsByStreamer = {}
    for streamer in allInputStreamers:
        timePairs = []
        inputSessionTimestampsByStreamer[streamer] = timePairs
        for session in inputSessionsByStreamer[streamer]:
            start, end = session.startTimestamp, session.endTimestamp
            if len(timePairs) == 0:
                timePairs.append([start, end])
            else:
                prevPair = timePairs[-1]
                if start == prevPair[1]:
                    prevPair[1] = end
                else:
                    timePairs.append([start, end])
    if logLevel >= 2:
        print("\n\n\nStep 6: ")
        pprint(inputSessionTimestampsByStreamer)

    # 7. Build a sorted array of unique timestamps from #6, truncated to those within the target streamer's first and
        # last sessions (inclusive)
    mainSessionsStartTime = mainSessionsOnTargetDate[0].startTimestamp
    mainSessionsEndTime = mainSessionsOnTargetDate[-1].endTimestamp
    uniqueTimestamps = set((mainSessionsStartTime, mainSessionsEndTime))
    for streamer in allInputStreamers:
        for timePair in inputSessionTimestampsByStreamer[streamer]:
            start, end = timePair
            if start > mainSessionsStartTime or startTimeMode == 'allOverlapStart':
                uniqueTimestamps.add(start)
            if end < mainSessionsEndTime or endTimeMode == 'allOverlapEnd':
                uniqueTimestamps.add(timePair[1])
    uniqueTimestampsSorted = sorted(uniqueTimestamps)
    allSessionsStartTime = uniqueTimestampsSorted[0]
    allSessionsEndTime = uniqueTimestampsSorted[-1]
    if logLevel >= 1:
        print("\n\n\nStep 7: ", allSessionsStartTime, allSessionsEndTime,
              mainSessionsStartTime, mainSessionsEndTime, uniqueTimestampsSorted)
        for ts in uniqueTimestampsSorted:
            print(convertToDatetime(ts))
        print(convertToDatetime(
            uniqueTimestampsSorted[-1])-convertToDatetime(uniqueTimestampsSorted[0]), end='\n\n')

    # 8. Build a len(#5) x len(#7)-1 matrix, where each row is the time between the n'th and n+1'th timestamp from #7
        # and the element in each column is either None or the indexed streamer's file(path) for that section of
        # time - should never be more than one
    numSegments = len(uniqueTimestampsSorted)-1
    segmentFileMatrix = [[None for i in range(
        len(allInputStreamers))] for j in range(numSegments)]
    segmentSessionMatrix = [[None for i in range(
        len(allInputStreamers))] for j in range(numSegments)]
    for segIndex in range(numSegments):
        # segmentsByStreamerIndex = segmentFileMatrix[segIndex]
        segmentStartTime = uniqueTimestampsSorted[segIndex]
        segmentEndTime = uniqueTimestampsSorted[segIndex+1]  # - 1

        def addOverlappingSessions(sessionsList, streamerIndex):
            for session in sessionsList:
                overlapStart = max(segmentStartTime, session.startTimestamp)
                overlapEnd = min(segmentEndTime, session.endTimestamp)
                overlapLength = max(0, overlapEnd - overlapStart)
                if overlapLength > 0:
                    if segmentFileMatrix[segIndex][streamerIndex] is None:
                        segmentFileMatrix[segIndex][streamerIndex] = session.file
                        segmentSessionMatrix[segIndex][streamerIndex] = [
                            session]
                    else:
                        segmentSessionMatrix[segIndex][streamerIndex].append(
                            session)
                        if logLevel >= 3:
                            print(segmentSessionMatrix[segIndex][streamerIndex],
                                  overlapStart, overlapEnd, segmentStartTime, segmentEndTime)
                        assert segmentFileMatrix[segIndex][streamerIndex] is session.file
        addOverlappingSessions(mainSessionsOnTargetDate, 0)
        for i in range(1, len(allInputStreamers)):
            addOverlappingSessions(
                inputSessionsByStreamer[allInputStreamers[i]], i)
    if logLevel >= 1:
        print("\n\n\nStep 8: ")
        if logLevel >= 4:
            pprint(segmentFileMatrix)
        print(allInputStreamers)

    # 9. Remove segments of secondary streamers still in games that main streamer has left
    if logLevel >= 1:
        print("\n\nStep 9:")

    def printSegmentMatrix(showGameChanges=True):
        if logLevel >= 1:
            print("\n\n")
            for i in range(len(segmentSessionMatrix)):
                if showGameChanges and i > 0:
                    prevRowGames = [
                        session.game for session in segmentSessionMatrix[i-1][0]]
                    currRowGames = [
                        session.game for session in segmentSessionMatrix[i][0]]
                    # if segmentSessionMatrix[i][0] != segmentSessionMatrix[i-1][0]:
                    if any((game not in currRowGames for game in prevRowGames)):
                        print('-'*(2*len(allInputStreamers)+1))
                print(f"[{' '.join(['x' if item is not None else ' ' for item in segmentSessionMatrix[i]])}]", i,
                      convertToDatetime(
                          uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[i]),
                      convertToDatetime(
                          uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[0]),
                      str(convertToDatetime(uniqueTimestampsSorted[i]))[:-6],
                      str(convertToDatetime(uniqueTimestampsSorted[i+1]))[:-6], sep=',')
    printSegmentMatrix(showGameChanges=True)
    # for i in range(len(segmentFileMatrix)):
    #    if segmentSessionMatrix[i][0] is None:
    #        tempMainGames = set()
    #    else:
    #        tempMainGames = set((session.game for session in segmentSessionMatrix[i][0]))
    #    tempGames = set((session.game for item in segmentSessionMatrix[i][1:] if item is not None for session in item))
    #    print(tempMainGames, tempGames, str(convertToDatetime(uniqueTimestampsSorted[i]))[:-6],
    #          str(convertToDatetime(uniqueTimestampsSorted[i+1]))[:-6])

    excludeTrimStreamerIndices = []
    mainStreamerGames = set(
        (session.game for row in segmentSessionMatrix if row[0] is not None for session in row[0] if session.game not in nongroupGames))
    for streamerIndex in range(1, len(allInputStreamers)):
        if not any((session.game in mainStreamerGames for row in segmentSessionMatrix if row[streamerIndex] is not None for session in row[streamerIndex])):
            # can have one brother in the session but not be the same as the one streaming
            if allInputStreamers[streamerIndex] != 'BonzaiBroz':
                excludeTrimStreamerIndices.append(streamerIndex)
            # If the trimming process would remove /all/ segments for the given streamer, exclude the streamer from
            # trimming because they probably just have a different game name listed
    if logLevel >= 2:
        print('Excluding from trimming:', excludeTrimStreamerIndices, [
              allInputStreamers[index] for index in excludeTrimStreamerIndices])

    if logLevel >= 1:
        print("\n\nStep 9.1:")
    if sessionTrimLookback >= 0:
        # Remove trailing footage from secondary sessions, for instance the main streamer changes games while part of the group stays on the previous game
        for i in range(0, len(segmentFileMatrix)):
            # print(len(segmentSessionMatrix[i-sessionTrimLookback:]))
            includeRowStart = max(0, i-sessionTrimLookback)
            includeRowEnd = min(len(segmentFileMatrix),
                                i+sessionTrimLookahead+1)
            if logLevel >= 2:
                print(includeRowStart, sessionTrimLookback, i)
                print(includeRowEnd, sessionTrimLookahead, i)
            rowGames = set(
                (session.game for session in segmentSessionMatrix[i][0] if segmentSessionMatrix[i][0] is not None))
            if logLevel >= 2:
                print('rowGames', rowGames)
            # print(segmentSessionMatrix[i-sessionTrimLookback])
            acceptedGames = set((session.game for row in segmentSessionMatrix[includeRowStart:includeRowEnd]
                                if row[0] is not None for session in row[0] if session.game not in nongroupGames))
            if logLevel >= 2:
                print('acceptedGames', acceptedGames)  # , end=' ')
            # main streamer has no sessions for segment, extend from previous segment with sessions
            if len(acceptedGames) == 0 and (startTimeMode == 'allOverlapStart' or endTimeMode == 'allOverlapEnd'):
                # expandedIncludeStart =
                raise Exception("Needs updating")
                if endTimeMode == 'allOverlapEnd':
                    for j in range(i-(sessionTrimLookback+1), 0, -1):
                        if logLevel >= 2:
                            print(f"j={j}")
                        if segmentSessionMatrix[j][0] is None:
                            continue
                        tempAcceptedGames = set(
                            (session.game for session in segmentSessionMatrix[j][0] if session.game not in nongroupGames))
                        if len(tempAcceptedGames) > 0:
                            acceptedGames = tempAcceptedGames
                            break
            if logLevel >= 2:
                print(acceptedGames, reduce(set.union,
                      (set((session.game for session in sessionList))
                       for sessionList in segmentSessionMatrix[i] if sessionList is not None),
                      set()))
            for streamerIndex in range(1, len(allInputStreamers)):
                if streamerIndex in excludeTrimStreamerIndices:
                    continue
                sessionList = segmentSessionMatrix[i][streamerIndex]
                if sessionList is None:
                    continue
                if not any((session.game in acceptedGames for session in sessionList)):
                    segmentSessionMatrix[i][streamerIndex] = None
                    segmentFileMatrix[i][streamerIndex] = None
        if logLevel >= 2:
            printSegmentMatrix(showGameChanges=True)
    elif sessionTrimLookbackSeconds > 0 or sessionTrimLookaheadSeconds > 0:
        # trim by seconds
        raise Exception("Not implemented yet")

    def splitRow(rowNum, timestamp):
        assert uniqueTimestampsSorted[rowNum] < timestamp < uniqueTimestampsSorted[rowNum+1]
        fileRowCopy = segmentFileMatrix[rowNum].copy()
        segmentFileMatrix.insert(rowNum, fileRowCopy)
        segmentRowCopy = [(None if sessions is None else sessions.copy())
                          for sessions in segmentSessionMatrix[rowNum]]
        segmentSessionMatrix.insert(rowNum, segmentRowCopy)
        uniqueTimestampsSorted.insert(rowNum+1, timestamp)
        numSegments += 1

    # TODO: fill in short gaps (<5 min?) in secondary streamers if possible
    if minGapSize > 0:
        if logLevel >= 1:
            print("\n\nStep 9.2:")
        for streamerIndex in range(1, len(allInputStreamers)):
            streamer = allInputStreamers[streamerIndex]
            gapLength = 0
            gapStart = -1
            lastState = (segmentFileMatrix[0][streamerIndex] is not None)
            for i in range(1, len(segmentFileMatrix)):
                curState = (segmentFileMatrix[i][streamerIndex] is not None)
                segmentDuration = uniqueTimestampsSorted[i +
                                                         1] - uniqueTimestampsSorted[i]
                if curState != lastState:
                    if curState:
                        # gap ending
                        if gapLength < minGapSize and gapStart != -1:
                            # assert gapStart > 0, f"i={i}, gapStart={str(gapStart)}, curState={curState}"
                            gapStartFile = segmentFileMatrix[gapStart -
                                                             1][streamerIndex]
                            gapEndFile = segmentFileMatrix[i][streamerIndex]
                            # if gapStartFile is gapEndFile:
                            # assert gapEndTime - gapStartTime == gapLength #TODO: replace gapLength with the subtraction everywhere
                            # gap starts and ends with the same file, can fill in gap easily
                            for j in range(gapStart, i):
                                segmentStartTime = uniqueTimestampsSorted[j]
                                segmentEndTime = uniqueTimestampsSorted[j]
                                missingSessions = [session for session in allStreamerSessions[streamer]
                                                   if session.startTimestamp <= segmentEndTime and session.endTimestamp >= segmentStartTime]
                                assert len(missingSessions) <= 1 or all((missingSessions[0].file == missingSessions[k].file for k in range(
                                    1, len(missingSessions)))), str(missingSessions)
                                if len(missingSessions) >= 1:
                                    segmentSessionMatrix[j][streamerIndex] = missingSessions
                                    segmentFileMatrix[j][streamerIndex] = missingSessions[0].file
                                else:
                                    assert len(
                                        missingSessions) == 0 and gapStartFile is not gapEndFile
                        gapStart = -1
                        gapLength = 0
                    else:
                        # gap starting
                        gapStart = i
                        gapLenth = segmentDuration
                if not curState:
                    gapLength += segmentDuration
                lastState = curState

    if logLevel >= 2:
        printSegmentMatrix()

    # 10. Remove streamers who have less than a minimum amount of time in the video
    if logLevel >= 1:
        print("\n\nStep 10:")
        print(allInputStreamers)
        print(allInputStreamersSortKey)
    for streamerIndex in range(len(allInputStreamers)-1, 0, -1):
        streamer = allInputStreamers[streamerIndex]
        streamerTotalTime = 0
        for i in range(len(segmentSessionMatrix)):
            if segmentSessionMatrix[i][streamerIndex] is not None:
                streamerTotalTime += uniqueTimestampsSorted[i+1] - \
                    uniqueTimestampsSorted[i]
        if logLevel >= 1:
            print(streamerIndex, streamer, streamerTotalTime)
        if streamerTotalTime < minimumTimeInVideo:
            if logLevel >= 1:
                print("Removing streamer", streamer)
            for i in range(len(segmentSessionMatrix)):
                del segmentSessionMatrix[i][streamerIndex]
                del segmentFileMatrix[i][streamerIndex]
            del allInputStreamers[streamerIndex]
            for key, val in allInputStreamersSortKey.items():
                if val > allInputStreamersSortKey[streamer]:
                    allInputStreamersSortKey[key] -= 1
            del allInputStreamersSortKey[streamer]
            del inputSessionTimestampsByStreamer[streamer]
            secondaryStreamers.remove(streamer)
            for session in inputSessionsByStreamer[streamer]:
                secondarySessionsArray.remove(session)
            del inputSessionsByStreamer[streamer]
    if logLevel >= 1:
        print(allInputStreamers, allInputStreamersSortKey)
        if logLevel >= 2:
            printSegmentMatrix()

    # 11. Combine adjacent segments that now have the same set of streamers
        print("\n\nStep 11:")
    # def compressRows():
    for i in range(numSegments-1, 0, -1):
        if logLevel >= 1:
            print(i)
        if all(((segmentFileMatrix[i][stIndex] is None) == (segmentFileMatrix[i-1][stIndex] is None) for stIndex in range(len(allInputStreamers)))):
            del segmentFileMatrix[i]
            sessionMergeRow = [None if segmentSessionMatrix[i][si] is None else set(
                segmentSessionMatrix[i-1][si]).union(set(segmentSessionMatrix[i][si])) for si in range(len(allInputStreamers))]
            segmentSessionMatrix[i-1] = [None if sessionMerge is None else sorted(
                sessionMerge, key=lambda x: x.startTimestamp) for sessionMerge in sessionMergeRow]
            del segmentSessionMatrix[i]
            tempTs = uniqueTimestampsSorted[i]
            if logLevel >= 1:
                print(
                    f"Combining segments {str(i)} and {str(i-1)}, dropping timestamp {str(tempTs)}")
            del uniqueTimestampsSorted[i]
            uniqueTimestamps.remove(tempTs)
            numSegments -= 1
    # compressRows()

    printSegmentMatrix()
    for i in range(len(segmentSessionMatrix)):
        if segmentSessionMatrix[i][0] is None:
            if logLevel >= 1:
                print([])
            continue
        tempMainGames = set(
            (session.game for session in segmentSessionMatrix[i][0]))
        tempGames = set(
            (session.game for item in segmentSessionMatrix[i][1:] if item is not None for session in item))
        if logLevel >= 1:
            print(tempMainGames, tempGames, str(convertToDatetime(uniqueTimestampsSorted[i]))[:-6],
                  str(convertToDatetime(uniqueTimestampsSorted[i+1]))[:-6])

    # 12. Build a sorted array of unique filepaths from #8 - these will become the input stream indexes
    inputFilesSorted = sorted(set([item for sublist in segmentFileMatrix for item in sublist if item is not None]),
                              key=lambda x: allInputStreamers.index(x.streamer))
    # 12a. Build reverse-lookup dictionary
    inputFileIndexes = {}
    for i in range(len(inputFilesSorted)):
        inputFileIndexes[inputFilesSorted[i]] = i
        # 12b. Build input options in order
    inputOptions = []
    inputVideoInfo = []
    for i in range(len(inputFilesSorted)):
        file = inputFilesSorted[i]
        if useHardwareAcceleration & HW_DECODE != 0:
            if maxHwaccelFiles == 0 or i < maxHwaccelFiles:
                decodeOptions = ACTIVE_HWACCEL_VALUES['decode_input_options']
                scaleOptions = ACTIVE_HWACCEL_VALUES['scale_input_options']
                inputOptions.extend(decodeOptions)
                # inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
                # inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
                if useHardwareAcceleration & HW_INPUT_SCALE != 0 and cutMode in ('trim', 'chunked') and scaleOptions is not None:
                    inputOptions.extend(scaleOptions)
                    # inputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
            # else:
            #    inputOptions.extend(('-threads', str(threadCount//2)))
        inputOptions.append('-i')
        if file.localVideoFile is not None:
            inputOptions.append(file.localVideoFile)
            if logLevel >= 1:
                print(file.localVideoFile)
            inputVideoInfo.append(file.getVideoFileInfo())
        else:
            inputOptions.append(file.videoFile)
            if logLevel >= 1:
                print(file.videoFile)
            inputVideoInfo.append(file.getVideoFileInfo())
    # nullAudioIndex = len(inputFilesSorted)
    if logLevel >= 1:
        print("\n\n\nStep 12: ", inputOptions)
    forceKeyframeTimes = [toFfmpegTimestamp(
        uniqueTimestampsSorted[i]-allSessionsStartTime) for i in range(1, numSegments)]
    keyframeOptions = ['-force_key_frames', ','.join(forceKeyframeTimes)]
    streamerAudioSampleRates = [None for i in range(len(allInputStreamers))]
    for i in range(len(inputFilesSorted)):
        file = inputFilesSorted[i]
        fileInfo = inputVideoInfo[i]
        streamerIndex = allInputStreamersSortKey[file.streamer]
        audioStreamInfo = [
            stream for stream in fileInfo['streams'] if stream['codec_type'] == 'audio'][0]
        audioRate = audioStreamInfo['sample_rate']
        streamerAudioSampleRates[streamerIndex] = audioRate
        if logLevel >= 2:
            print(file.streamer, audioRate)
    nullAudioStreamsBySamplerates = {}
    for samplerate in set(streamerAudioSampleRates):
        rateStr = str(samplerate)
        inputIndex = len([x for x in inputOptions if x == '-i'])
        assert inputIndex == len(inputFilesSorted) + \
            len(nullAudioStreamsBySamplerates)
        inputOptions.extend(('-f',  'lavfi', '-i', f'anullsrc=r={rateStr}'))
        nullAudioStreamsBySamplerates[rateStr] = inputIndex

    # 13. Use #5 and #12 to build output stream mapping orders and build final command along with #12 and #11
    segmentTileCounts = [len(list(filter(lambda x: x is not None, row)))
                         for row in segmentFileMatrix]
    maxSegmentTiles = max(segmentTileCounts)
    maxTileWidth = calcTileWidth(maxSegmentTiles)
    outputResolution = outputResolutions[maxTileWidth]
    outputResolutionStr = f"{str(outputResolution[0])}:{str(outputResolution[1])}"
    outputMapOptions = ['-map', '[vout]']
    outputMetadataOptions = []
    for streamerIndex in range(len(allInputStreamers)):
        outputMapOptions.extend(('-map', f"[aout{streamerIndex}]"))
        streamerName = allInputStreamers[streamerIndex]
        outputMetadataOptions.extend((f"-metadata:s:a:{streamerIndex}",
                                      f"title=\"{str(streamerIndex+1)+' - ' if drawLabels else ''}{streamerName}\"",
                                      f"-metadata:s:a:{streamerIndex}",
                                      "language=eng"))
    codecOptions = ["-c:a", "aac",
                    "-c:v", outputCodec,
                    "-s", outputResolutionStr]
    if outputCodec in ('libx264', 'h264_nvenc'):
        codecOptions.extend(("-profile:v", "high",
                             # "-maxrate",outputBitrates[maxTileWidth],
                             # "-bufsize","4M",
                             "-preset", encodingSpeedPreset,
                             "-crf", "22",
                             ))
        if REDUCED_MEMORY:
            codecOptions.extend('-rc-lookahead', '20', '-g', '60')
    elif outputCodec in ('libx265', 'hevc_nvenc'):
        codecOptions.extend((
            "-preset", encodingSpeedPreset,
            "-crf", "26",
            "-tag:v", "hvc1"
        ))
        if REDUCED_MEMORY:
            print("Reduced memory mode not available yet for libx265 codec")
    threadOptions = ['-threads', str(threadCount),
                     '-filter_threads', str(threadCount),
                     '-filter_complex_threads', str(threadCount)] if useHardwareAcceleration else []
    uploadFilter = "hwupload" + ACTIVE_HWACCEL_VALUES['upload_filter']
    downloadFilter = "hwdownload,format=pix_fmts=yuv420p"
    timeFilter = f"setpts={vpts}"

    # 14. For each row of #8:
    # filtergraphStringSegments = []
    # filtergraphStringSegmentsV2 = []
    if logLevel >= 1:
        print("\n\n\nStep 13.v2: ", segmentTileCounts,
              maxSegmentTiles, outputResolution)
    # v2()

    def filtergraphSegmentVersion():
        filtergraphParts = []
        inputSegmentNumbers = [[None for i in range(
            len(allInputStreamers))] for j in range(numSegments)]
        for fileIndex in range(len(inputFilesSorted)):
            inputFile: SourceFile = inputFilesSorted[fileIndex]
            fileInfo = inputVideoInfo[fileIndex]
            videoStreamInfo = [
                stream for stream in fileInfo['streams'] if stream['codec_type'] == 'video'][0]
            fpsRaw = videoStreamInfo['avg_frame_rate'].split('/')
            fpsActual = float(fpsRaw[0]) / float(fpsRaw[1])
            if logLevel >= 2:
                print(inputFile.videoFile, fpsRaw, fpsActual, fpsActual == 60)
            fileStartTime = inputFile.startTimestamp
            fileEndTime = inputFile.endTimestamp
            timestamps = []
            segmentIndex = 0
            segmentsPresent = [i for i in range(numSegments) if any(
                (segmentFileMatrix[i][j] is inputFile for j in range(len(allInputStreamers))))]
            if logLevel >= 3:
                print('\n', inputFile.videoFile, segmentsPresent)
            streamerIndex = allInputStreamersSortKey[inputFile.streamer]
            # for segments that are not wanted, typically leading or trailing ones
            nullVSinkFiltergraphs = []
            # for segments that are not wanted, typically leading or trailing ones
            nullASinkFiltergraphs = []
            for matrixIndex in segmentsPresent:
                segmentStartTime = uniqueTimestampsSorted[matrixIndex]
                segmentEndTime = uniqueTimestampsSorted[matrixIndex+1]  # - 1
                startDiff = segmentStartTime - fileStartTime
                # segment is the start of a series of used segments
                if (matrixIndex-1) not in segmentsPresent:
                    if startDiff > 0:  # segment starts partway through the video, need to discard first segment
                        # if matrixIndex == 0:
                        nullVSegName = f"file{fileIndex}V{len(timestamps)}"
                        nullVSinkFiltergraphs.append(
                            f"[{nullVSegName}] nullsink")
                        nullASegName = f"file{fileIndex}A{len(timestamps)}"
                        nullASinkFiltergraphs.append(
                            f"[{nullASegName}] anullsink")
                        timestamps.append(startDiff)
                    inputSegmentNumbers[matrixIndex][allInputStreamersSortKey[inputFile.streamer]] = (
                        len(timestamps), fileIndex)
                # segment is not the start of a series of used segments (could be middle or end)
                else:
                    assert startDiff > 0  # segment starts partway through the video
                    timestamps.append(startDiff)
                    inputSegmentNumbers[matrixIndex][allInputStreamersSortKey[inputFile.streamer]] = (
                        len(timestamps), fileIndex)
            lastSegment = segmentsPresent[-1]
            lastSegmentEndTime = uniqueTimestampsSorted[lastSegment+1]
            endDiff = fileEndTime - lastSegmentEndTime
            if endDiff > 0:
                if logLevel >= 2:
                    print('endDiff', endDiff)
                timestamps.append(lastSegmentEndTime-fileStartTime)
                nullVSegName = f"file{fileIndex}V{len(timestamps)}"
                nullVSinkFiltergraphs.append(f"[{nullVSegName}] nullsink")
                nullASegName = f"file{fileIndex}A{len(timestamps)}"
                nullASinkFiltergraphs.append(f"[{nullASegName}] anullsink")
            segmentFilter = f"segment=timestamps={'|'.join((str(ts) for ts in timestamps))}"
            if logLevel >= 2:
                print(segmentFilter)
            fpsFilter = f"fps=fps=60:round=near, " if fpsActual != 60 else ''
            inputVideoFiltergraph = f"[{fileIndex}:v] {fpsFilter}{segmentFilter} [{']['.join((f'file{fileIndex}V{i}' for i in range(len(timestamps)+1)))}]"
            inputAudioFiltergraph = f"[{fileIndex}:a] a{segmentFilter} [{']['.join((f'file{fileIndex}A{i}' for i in range(len(timestamps)+1)))}]"
            filtergraphParts.extend(
                (inputVideoFiltergraph, inputAudioFiltergraph))
            filtergraphParts.extend(nullVSinkFiltergraphs)
            filtergraphParts.extend(nullASinkFiltergraphs)
        assert all((all(((inputSegmentNumbers[i][j] is None) == (
            segmentFileMatrix[i][j] is None) for j in range(len(allInputStreamers)))) for i in range(numSegments)))
        for segIndex in range(numSegments):
            segmentStartTime = uniqueTimestampsSorted[segIndex]
            segmentEndTime = uniqueTimestampsSorted[segIndex+1]
            segmentDuration = segmentEndTime - segmentStartTime
            rowSegmentNumbers = []
            numTiles = segmentTileCounts[segIndex]
            tileResolution, segmentResolution = calcResolutions(
                numTiles, maxSegmentTiles)
            if logLevel >= 2:
                print("\n\nStep 13a.v2: ", segIndex, numTiles, tileResolution,
                      segmentResolution, inputSegmentNumbers[segIndex])
            rowVideoSegmentNames = []
            for streamerIndex in range(len(allInputStreamers)):
                temp = inputSegmentNumbers[segIndex][streamerIndex]
                if logLevel >= 2:
                    print(temp)
                if temp is not None:
                    fileSegNum, fileIndex = temp
                    fileInfo = inputVideoInfo[fileIndex]
                    videoStreamInfo = [
                        stream for stream in fileInfo['streams'] if stream['codec_type'] == 'video'][0]
                    height = videoStreamInfo['height']
                    width = videoStreamInfo['width']
                    isSixteenByNine = (height / 9.0) == (width / 16.0)
                    originalResolution = f"{width}:{height}"
                    needToScale = originalResolution != tileResolution
                    if logLevel >= 3:
                        print(inputFilesSorted[fileIndex].videoFile, fileIndex,
                              originalResolution, originalResolution == tileResolution)
                    inputVSegName = f"file{fileIndex}V{fileSegNum}"
                    outputVSegName = f"seg{segIndex}V{streamerIndex}"
                    labelFilter = f", drawtext=text='{str(streamerIndex+1)} {allInputStreamers[streamerIndex]}':fontsize=40:fontcolor=white:x=100:y=10:shadowx=4:shadowy=4" if drawLabels else ''
                    useHwFilterAccel = useHardwareAcceleration & HW_INPUT_SCALE != 0 and (
                        maxHwaccelFiles == 0 or fileIndex < maxHwaccelFiles)
                    uploadFilter, downloadFilter = (f", hwupload{ACTIVE_HWACCEL_VALUES['upload_filter']}",
                                                    f", hwdownload,format=pix_fmts=yuv420p") if useHwFilterAccel and (needToScale or not isSixteenByNine) else ('', '')
                    scaleFilter = f", scale{'_npp' if useHwFilterAccel else ''}={tileResolution}:force_original_aspect_ratio=decrease:{'format=yuv420p:' if useHwFilterAccel else ''}eval=frame" if needToScale else ''
                    padFilter = f", pad{'_opencl' if useHwFilterAccel else ''}={tileResolution}:-1:-1:color=black" if not isSixteenByNine else ''
                    videoFiltergraph = f"[{inputVSegName}] setpts={vpts}{uploadFilter}{scaleFilter}{padFilter}{downloadFilter}{labelFilter} [{outputVSegName}]"
                    # if :
                    #    videoFiltergraph = f"[{inputVSegName}] setpts={vpts}, hwupload_cuda, scale_npp={tileResolution}:force_original_aspect_ratio=decrease:format=yuv420p:eval=frame, pad_opencl={tileResolution}:-1:-1:color=black, hwdownload, format=pix_fmts=yuv420p{labelFilter}, [{outputVSegName}]"
                    # else:
                    #    videoFiltergraph = f"[{inputVSegName}] setpts={vpts}, scale={tileResolution}:force_original_aspect_ratio=decrease:eval=frame, pad={tileResolution}:-1:-1:color=black{labelFilter} [{outputVSegName}]"
                    filtergraphParts.append(videoFiltergraph)
                    rowVideoSegmentNames.append(outputVSegName)
                else:
                    audioRate = streamerAudioSampleRates[streamerIndex]
                    nullAudioIndex = nullAudioStreamsBySamplerates[str(
                        audioRate)]
                    emptyAudioFiltergraph = f"[{nullAudioIndex}] atrim=duration={segmentDuration} [seg{segIndex}A{streamerIndex}]"
                    filtergraphParts.append(emptyAudioFiltergraph)
                    if logLevel >= 4:
                        print("\n\nStep 13b.v2: ", segIndex,
                              streamerIndex, emptyAudioFiltergraph)
            # 13c. Build xstack intermediate video segments
            numRowSegments = len(rowVideoSegmentNames)
            # should have at least one source file for each segment, otherwise we have a gap we need to account for
            assert numRowSegments > 0
            if numRowSegments > 1:
                rowTileWidth = calcTileWidth(numRowSegments)
                if logLevel >= 2:
                    print(segmentResolution, outputResolutionStr, numRowSegments,
                          rowTileWidth*(rowTileWidth-1), rowTileWidth)
                    print(segmentResolution != outputResolutionStr,
                          numRowSegments <= rowTileWidth*(rowTileWidth-1))
                scaleToFitFilter = f", scale={outputResolutionStr}:force_original_aspect_ratio=decrease:eval=frame" if segmentResolution != outputResolutionStr else ''
                padFilter = f", pad={outputResolutionStr}:-1:-1:color=black" if numRowSegments <= rowTileWidth*(
                    rowTileWidth-1) else ''
                xstackString = f"[{']['.join(rowVideoSegmentNames)}]xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}{scaleToFitFilter}{padFilter} [vseg{segIndex}]"
                filtergraphParts.append(xstackString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", xstackString, segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(
                        rowTileWidth-1), (segmentResolution != outputResolutionStr), (numRowSegments <= rowTileWidth*(rowTileWidth-1)))
            else:
                filtergraphString = f"[{rowVideoSegmentNames[0]}] copy [vseg{segIndex}]"
                filtergraphParts.append(filtergraphString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", filtergraphString,
                          segmentResolution, outputResolutionStr, numRowSegments)

        # 15. Build concat statement of intermediate video and audio segments
        videoConcatFiltergraph = f"[{']['.join(('vseg'+str(n) for n in range(numSegments)))}] concat=n={numSegments}:v=1:a=0 [vout]"
        filtergraphParts.append(videoConcatFiltergraph)
        if logLevel >= 3:
            print("\n\n\nStep 14: ", videoConcatFiltergraph)

        # 16. Use #5, #7 and #12a to build individual audio output segments
        for streamerIndex in range(len(allInputStreamers)):
            audioConcatList = []
            for n in range(numSegments):
                numbers = inputSegmentNumbers[n][streamerIndex]
                if numbers is None:
                    audioConcatList.append(f"seg{n}A{streamerIndex}")
                else:
                    fileSegNum, fileIndex = numbers
                    audioConcatList.append(f"file{fileIndex}A{fileSegNum}")
            audioConcatFiltergraph = f"[{']['.join(audioConcatList)}] concat=n={numSegments}:v=0:a=1 [aout{streamerIndex}]"
            filtergraphParts.append(audioConcatFiltergraph)
            if logLevel >= 3:
                print("\n\n\nStep 15: ", streamerIndex, audioConcatFiltergraph)
        if logLevel >= 2:
            pprint(inputSegmentNumbers)
            pprint(filtergraphParts)
        # print(nullVSinkFiltergraphs, nullASinkFiltergraphs, segmentFiltergraphs)
        completeFiltergraph = " ; ".join(filtergraphParts)
        return [reduce(list.__add__, [[f"{ffmpegPath}ffmpeg"],
                inputOptions,
                threadOptions,
                ['-filter_complex', completeFiltergraph],
                keyframeOptions,
                outputMapOptions,
                outputMetadataOptions,
                codecOptions,
                ["-movflags", "faststart", outputFile]])]

    if logLevel >= 1:
        print("\n\n\nStep 13.v1: ", segmentTileCounts,
              maxSegmentTiles, outputResolution)

    def getScaleAlgorithm(inputDim, outputDim, useHwScaling):
        if outputDim > inputDim:  # upscaling
            return '' if useHwScaling else ':flags=lanczos'
        elif outputDim < inputDim:
            return ':interp_algo=super' if useHwScaling else ''  # ':flags=area'
        else:  # outputDim == inputDim
            return ''

    # v1
    def filtergraphTrimVersion():  # uniqueTimestampsSorted, allInputStreamers, segmentFileMatrix, segmentSessionMatrix
        filtergraphParts = []
        for segIndex in range(numSegments):
            segmentStartTime = uniqueTimestampsSorted[segIndex]
            segmentEndTime = uniqueTimestampsSorted[segIndex+1]
            segmentDuration = segmentEndTime - segmentStartTime
            numTiles = segmentTileCounts[segIndex]
            tileResolution, segmentResolution = calcResolutions(
                numTiles, maxSegmentTiles)
            # rowFiltergraphSegments = []
            # 13a. Build array of filepaths-streamer index pairs using #5 that appear in the row, without Nones
            # 13b. Use original start timestamp of each file and #7 to determine starting time within file and add to
            # info array elements
            if logLevel >= 2:
                print("\n\nStep 13a: ", segIndex, segmentStartTime,
                      segmentEndTime, numTiles, tileResolution, segmentResolution)
            rowVideoSegmentNames = []
            for streamerIndex in range(len(allInputStreamers)):
                file = segmentFileMatrix[segIndex][streamerIndex]
                # 13b. Use #10a&b and #9a to build intermediate segments
                if file is not None:
                    startOffset = segmentStartTime - file.startTimestamp
                    endOffset = segmentEndTime - file.startTimestamp
                    inputIndex = inputFileIndexes[file]
                    videoSegmentName = f"seg{segIndex}V{streamerIndex}"
                    audioSegmentName = f"seg{segIndex}A{streamerIndex}"
                    audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts={apts} [{audioSegmentName}]"
                    fileInfo = inputVideoInfo[inputIndex]
                    videoStreamInfo = [
                        stream for stream in fileInfo['streams'] if stream['codec_type'] == 'video'][0]
                    height = videoStreamInfo['height']
                    width = videoStreamInfo['width']
                    isSixteenByNine = (height / 9.0) == (width / 16.0)
                    originalResolution = f"{width}:{height}"
                    needToScale = originalResolution != tileResolution
                    # print(inputFilesSorted[fileIndex].videoFile, fileIndex, originalResolution, originalResolution == tileResolution)
                    fpsRaw = videoStreamInfo['avg_frame_rate'].split('/')
                    fpsActual = float(fpsRaw[0]) / float(fpsRaw[1])
                    # print(inputFile.videoFile, fpsRaw, fpsActual, fpsActual==60)
                    useHwFilterAccel = useHardwareAcceleration & HW_INPUT_SCALE != 0 and (
                        maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles)
                    scaleAlgo = getScaleAlgorithm(height, int(
                        tileResolution.split(':')[0]), useHwFilterAccel)
                    scaleSuffix = ACTIVE_HWACCEL_VALUES['scale_filter'] if useHwFilterAccel else ''
                    padSuffix = ACTIVE_HWACCEL_VALUES['pad_filter'] if useHwFilterAccel else ''
                    scaleFilter = f"scale{scaleSuffix}={tileResolution}:force_original_aspect_ratio=decrease:{'format=yuv420p:' if useHwFilterAccel else ''}eval=frame{scaleAlgo}" if needToScale else ''
                    padFilter = f"pad{padSuffix}={tileResolution}:-1:-1:color=black" if not isSixteenByNine else ''
                    fpsFilter = f"fps=fps=60:round=near" if fpsActual != 60 else ''
                    labelFilter = f"drawtext=text='{str(streamerIndex+1)} {file.streamer}':fontsize=40:fontcolor=white:x=100:y=10:shadowx=4:shadowy=4" if drawLabels else ''
                    trimFilter = f"trim={startOffset}:{endOffset}"
                    # timeFilter = f"setpts={vpts}"
                    filtergraphBody = None
                    if needToScale or not isSixteenByNine:
                        if useHardwareAcceleration == 3 and (maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [
                                scaleFilter, padFilter, downloadFilter, fpsFilter, trimFilter, timeFilter, labelFilter]
                        elif useHardwareAcceleration == 2 and (maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [fpsFilter, trimFilter, timeFilter, uploadFilter,
                                               scaleFilter, padFilter, downloadFilter, labelFilter]
                        elif useHardwareAcceleration == 1 and (maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [
                                fpsFilter, trimFilter, timeFilter, scaleFilter, padFilter, labelFilter]
                        elif useHardwareAcceleration >= 4:
                            raise Exception("Not implemented yet")
                    if filtergraphBody is None:
                        filtergraphBody = [
                            trimFilter, timeFilter, fpsFilter, scaleFilter, padFilter, labelFilter]
                    videoFiltergraph = f"[{inputIndex}:v] {', '.join([segment for segment in filtergraphBody if segment != ''])} [{videoSegmentName}]"

                    filtergraphParts.append(videoFiltergraph)
                    filtergraphParts.append(audioFiltergraph)
                    rowVideoSegmentNames.append(videoSegmentName)
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex, file, startOffset,
                              endOffset, inputIndex, streamerIndex, videoSegmentName, audioSegmentName)
                else:
                    audioRate = streamerAudioSampleRates[streamerIndex]
                    nullAudioIndex = nullAudioStreamsBySamplerates[str(
                        audioRate)]
                    emptyAudioFiltergraph = f"[{nullAudioIndex}] atrim=duration={segmentDuration} [seg{segIndex}A{streamerIndex}]"
                    filtergraphParts.append(emptyAudioFiltergraph)
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex)
            # 13c. Build xstack intermediate video segments
            numRowSegments = len(rowVideoSegmentNames)
            # should have at least one source file for each segment, otherwise we have a gap we need to account for
            assert numRowSegments > 0
            if numRowSegments > 1:
                rowTileWidth = calcTileWidth(numRowSegments)
                segmentRes = [int(x) for x in segmentResolution.split(':')]
                scaleToFitFilter = f", scale={outputResolutionStr}:force_original_aspect_ratio=decrease:eval=frame" if segmentResolution != outputResolutionStr else ''
                padFilter = f", pad={outputResolutionStr}:-1:-1:color=black" if numRowSegments <= rowTileWidth*(
                    rowTileWidth-1) else ''
                xstackString = f"[{']['.join(rowVideoSegmentNames)}] xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}{scaleToFitFilter}{padFilter} [vseg{segIndex}]"
                filtergraphParts.append(xstackString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", xstackString, segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(
                        rowTileWidth-1), (segmentResolution != outputResolutionStr), (numRowSegments <= rowTileWidth*(rowTileWidth-1)))
            else:
                filtergraphString = f"[{rowVideoSegmentNames[0]}] copy [vseg{segIndex}]"
                filtergraphParts.append(filtergraphString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", filtergraphString,
                          segmentResolution, outputResolutionStr, numRowSegments)

        # 15. Build concat statement of intermediate video and audio segments
        videoConcatFiltergraph = f"[{']['.join(('vseg'+str(n) for n in range(numSegments)))}] concat=n={numSegments}:v=1:a=0 [vout]"
        filtergraphParts.append(videoConcatFiltergraph)
        if logLevel >= 3:
            print("\n\n\nStep 14: ", videoConcatFiltergraph)

        # 16. Use #5, #7 and #12a to build individual audio output segments
        for streamerIndex in range(len(allInputStreamers)):
            audioConcatFiltergraph = f"[{']['.join((''.join(('seg',str(n),'A',str(streamerIndex))) for n in range(numSegments)))}] concat=n={numSegments}:v=0:a=1 [aout{streamerIndex}]"
            filtergraphParts.append(audioConcatFiltergraph)
            if logLevel >= 3:
                print("\n\n\nStep 15: ", streamerIndex, audioConcatFiltergraph)
        # if logLevel >= 3:
        #    for fss in filtergraphStringSegments:
        #        print(fss)
        completeFiltergraph = " ; ".join(filtergraphParts)
        return [reduce(list.__add__, [[f"{ffmpegPath}ffmpeg"],
                inputOptions,
                threadOptions,
                ['-filter_complex', completeFiltergraph],
                keyframeOptions,
                outputMapOptions,
                outputMetadataOptions,
                codecOptions,
                ["-movflags", "faststart", outputFile]])]

    ####################
    ##  V3 - Chunked  ##
    ####################
    def filtergraphChunkedVersion():  # break it into multiple commands in an effort to limit memory usage
        print("CHUNKED", numSegments)
        commandList = []
        intermediateFilepaths = [os.path.join(
            localBasepath, 'temp', f"{mainStreamer} - {str(targetDate)} - part {i}.mkv") for i in range(numSegments)]
        audioFiltergraphParts = []
        for segIndex in range(numSegments):
            filtergraphParts = []
            segmentStartTime = uniqueTimestampsSorted[segIndex]
            segmentEndTime = uniqueTimestampsSorted[segIndex+1]
            segmentDuration = segmentEndTime - segmentStartTime
            numTiles = segmentTileCounts[segIndex]
            tileResolution, segmentResolution = calcResolutions(
                numTiles, maxSegmentTiles)
            # rowFiltergraphSegments = []
            # 13a. Build array of filepaths-streamer index pairs using #5 that appear in the row, without Nones
            # 13b. Use original start timestamp of each file and #7 to determine starting time within file and add to
            # info array elements
            if logLevel >= 2:
                print("\n\nStep 13a: ", segIndex, segmentStartTime,
                      segmentEndTime, numTiles, tileResolution, segmentResolution)
            rowVideoSegmentNames = []
            rowInputFileCount = 0
            rowFiles = [file for file in segmentFileMatrix[segIndex]
                        if file is not None]
            neededNullSampleRates = set()
            numFilesInRow = len(rowFiles)
            for streamerIndex in range(len(allInputStreamers)):
                if segmentFileMatrix[segIndex][streamerIndex] is None:
                    neededNullSampleRates.add(
                        streamerAudioSampleRates[streamerIndex])
            rowNullAudioStreamsBySamplerates = {}
            nullAudioInputOptions = []
            for samplerate in neededNullSampleRates:
                rateStr = str(samplerate)
                audioInputIndex = numFilesInRow + \
                    len(rowNullAudioStreamsBySamplerates)
                nullAudioInputOptions.extend(
                    ('-f',  'lavfi', '-i', f'anullsrc=r={rateStr}'))
                rowNullAudioStreamsBySamplerates[rateStr] = audioInputIndex

            rowInputOptions = []
            for streamerIndex in range(len(allInputStreamers)):
                file = segmentFileMatrix[segIndex][streamerIndex]
                videoSegmentName = f"seg{segIndex}V{streamerIndex}"
                audioSegmentName = f"seg{segIndex}A{streamerIndex}"
                # 13b. Use #10a&b and #9a to build intermediate segments
                if file is not None:
                    startOffset = segmentStartTime - file.startTimestamp
                    endOffset = segmentEndTime - file.startTimestamp
                    inputIndex = rowInputFileCount
                    fileIndex = inputFileIndexes[file]
                    # audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts={apts} [{audioSegmentName}]"
                    fileInfo = inputVideoInfo[fileIndex]
                    videoStreamInfo = [
                        stream for stream in fileInfo['streams'] if stream['codec_type'] == 'video'][0]
                    height = videoStreamInfo['height']
                    width = videoStreamInfo['width']
                    isSixteenByNine = (height / 9.0) == (width / 16.0)
                    originalResolution = f"{width}:{height}"
                    needToScale = originalResolution != tileResolution
                    if logLevel >= 3:
                        print(inputFilesSorted[fileIndex].videoFile, inputIndex,
                              originalResolution, tileResolution, originalResolution == tileResolution)
                    fpsRaw = videoStreamInfo['avg_frame_rate'].split('/')
                    fpsActual = float(fpsRaw[0]) / float(fpsRaw[1])
                    if useHardwareAcceleration & HW_DECODE != 0:
                        if maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles:
                            decodeOptions = ACTIVE_HWACCEL_VALUES['decode_input_options']
                            scaleOptions = ACTIVE_HWACCEL_VALUES['scale_input_options']
                            inputOptions.extend(decodeOptions)
                            # inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
                            # inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
                            if useHardwareAcceleration & HW_INPUT_SCALE != 0 and scaleOptions is not None:
                                inputOptions.extend(scaleOptions)
                            #    rowInputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
                        # else:
                        #    rowInputOptions.extend(('-threads', str(threadCount//2)))
                    if startOffset != 0:
                        rowInputOptions.extend(('-ss', str(startOffset)))
                    rowInputOptions.append('-i')
                    if file.localVideoFile is not None:
                        rowInputOptions.append(file.localVideoFile)
                    else:
                        rowInputOptions.append(file.videoFile)
                    useHwFilterAccel = useHardwareAcceleration & HW_INPUT_SCALE != 0 and (
                        maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles)
                    # print(file.videoFile, fpsRaw, fpsActual, fpsActual==60)
                    tileHeight = int(tileResolution.split(':')[1])
                    if logLevel >= 3:
                        print(
                            f"tileHeight={tileHeight}, video height={height}")
                    # if tileHeight > height: #upscaling
                    #    scaleAlgo = '' if useHwFilterAccel else ':flags=lanczos'
                    # elif tileHeight < height:
                    #    scaleAlgo = ':interp_algo=super' if useHwFilterAccel else '' #':flags=area'
                    # else:
                    #    scaleAlgo = ''
                    scaleAlgo = getScaleAlgorithm(
                        height, tileHeight, useHwFilterAccel)
                    scaleSuffix = ACTIVE_HWACCEL_VALUES['scale_filter'] if useHwFilterAccel else ''
                    padSuffix = ACTIVE_HWACCEL_VALUES['pad_filter'] if useHwFilterAccel else ''
                    scaleFilter = f"scale{scaleSuffix}={tileResolution}:force_original_aspect_ratio=decrease:{'format=yuv420p:' if useHwFilterAccel else ''}eval=frame{scaleAlgo}" if needToScale else ''
                    padFilter = f"pad{padSuffix}={tileResolution}:-1:-1:color=black" if not isSixteenByNine else ''
                    fpsFilter = f"fps=fps=60:round=near" if fpsActual != 60 else ''
                    labelFilter = f"drawtext=text='{str(streamerIndex+1)} {file.streamer}':fontsize=40:fontcolor=white:x=100:y=10:shadowx=4:shadowy=4" if drawLabels else ''
                    # trimFilter = f"trim={startOffset}:{endOffset}"
                    trimFilter = f"trim=duration={str(segmentDuration)}"
                    filtergraphBody = None
                    if needToScale or not isSixteenByNine:
                        mask = HW_DECODE | HW_INPUT_SCALE
                        if useHardwareAcceleration & mask == HW_DECODE and (maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [
                                fpsFilter, trimFilter, timeFilter, scaleFilter, padFilter, labelFilter]
                        elif useHardwareAcceleration & mask == HW_INPUT_SCALE and (maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [fpsFilter, trimFilter, timeFilter, uploadFilter,
                                               scaleFilter, padFilter, downloadFilter, labelFilter]
                        elif useHardwareAcceleration & mask == (HW_DECODE | HW_INPUT_SCALE) and (maxHwaccelFiles == 0 or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [
                                scaleFilter, padFilter, downloadFilter, fpsFilter, trimFilter, timeFilter, labelFilter]
                        # elif useHardwareAcceleration >= 4:
                        #    raise Exception("Not implemented yet")
                    if filtergraphBody is None:
                        filtergraphBody = [
                            trimFilter, timeFilter, fpsFilter, scaleFilter, padFilter, labelFilter]
                    videoFiltergraph = f"[{inputIndex}:v] {', '.join([segment for segment in filtergraphBody if segment != ''])} [{videoSegmentName}]"
                    # audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts={apts} [{audioSegmentName}]"
                    audioFiltergraph = f"[{inputIndex}:a] a{trimFilter}, a{timeFilter} [{audioSegmentName}]"

                    filtergraphParts.append(videoFiltergraph)
                    filtergraphParts.append(audioFiltergraph)
                    rowVideoSegmentNames.append(videoSegmentName)
                    rowInputFileCount += 1
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex, file, startOffset,
                              endOffset, inputIndex, streamerIndex, videoSegmentName, audioSegmentName)
                else:
                    audioRate = streamerAudioSampleRates[streamerIndex]
                    nullAudioIndex = rowNullAudioStreamsBySamplerates[str(
                        audioRate)]
                    emptyAudioFiltergraph = f"[{nullAudioIndex}] atrim=duration={segmentDuration} [{audioSegmentName}]"
                    filtergraphParts.append(emptyAudioFiltergraph)
                    # audioFiltergraphParts.append(emptyAudioFiltergraph)
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex)
            # 13c. Build xstack intermediate video segments
            numRowSegments = len(rowVideoSegmentNames)
            assert numFilesInRow == numRowSegments
            # should have at least one source file for each segment, otherwise we have a gap we need to account for
            assert numRowSegments > 0
            rowInputOptions.extend(nullAudioInputOptions)
            if numRowSegments > 1:
                rowTileWidth = calcTileWidth(numRowSegments)
                segmentRes = [int(x) for x in segmentResolution.split(':')]
                useHwOutscaleAccel = useHardwareAcceleration & HW_OUTPUT_SCALE != 0
                scaleSuffix = ACTIVE_HWACCEL_VALUES['scale_filter'] if useHwOutscaleAccel else ''
                padSuffix = ACTIVE_HWACCEL_VALUES['pad_filter'] if useHwOutscaleAccel else ''
                scaleToFitFilter = f"scale{scaleSuffix}={outputResolutionStr}:force_original_aspect_ratio=decrease:eval=frame" if segmentResolution != outputResolutionStr else ''
                padFilter = f"pad{padSuffix}={outputResolutionStr}:-1:-1:color=black" if numRowSegments <= rowTileWidth*(
                    rowTileWidth-1) else ''
                xstackFilter = f"xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}"
                # xstackString = f"[{']['.join(rowVideoSegmentNames)}] xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}{scaleToFitFilter}{padFilter}{uploadFilter if useHardwareAcceleration&HW_ENCODE!=0 else ''} [vseg{segIndex}]"
                if useHardwareAcceleration & HW_ENCODE != 0:
                    if useHwOutscaleAccel:
                        xstackBody = [xstackFilter, uploadFilter,
                                      scaleToFitFilter, padFilter]
                    else:
                        xstackBody = [xstackFilter,
                                      scaleToFitFilter, padFilter, uploadFilter]
                else:
                    xstackBody = [xstackFilter, scaleToFitFilter, padFilter]
                xstackString = f"[{']['.join(rowVideoSegmentNames)}] {', '.join([x for x in xstackBody if x != ''])} [vseg{segIndex}]"
                filtergraphParts.append(xstackString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", xstackString, segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(
                        rowTileWidth-1), (segmentResolution != outputResolutionStr), (numRowSegments <= rowTileWidth*(rowTileWidth-1)))
            else:
                filtergraphString = f"[{rowVideoSegmentNames[0]}] copy [vseg{segIndex}]"
                filtergraphParts.append(filtergraphString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", filtergraphString,
                          segmentResolution, outputResolutionStr, numRowSegments)
            # print(filtergraphParts)
            commandList.append(reduce(list.__add__, [[f"{ffmpegPath}ffmpeg"],
                                                     rowInputOptions,
                                                     threadOptions,
                                                     ['-filter_complex',
                                                         ' ; '.join(filtergraphParts)],
                                                     ['-map',
                                                         f"[vseg{segIndex}]"],
                                                     reduce(list.__add__, [
                                                         ['-map', f'[seg{str(segIndex)}A{str(streamerIndex)}]'] for streamerIndex in range(len(allInputStreamers))
                                                     ]),
                                                     # outputMetadataOptions,
                                                     codecOptions,
                                                     ["-movflags", "faststart", intermediateFilepaths[segIndex]]]))
        # 15. Build concat statement of intermediate video and audio segments

        class LazyConcatFile:
            def __init__(self, contents):
                self.contents = contents
                self.filepath = None

            def __repr__(self):
                if self.filepath is None:
                    while self.filepath is None or os.path.isfile(self.filepath):
                        self.filepath = f"./ffmpegConcatList{random.randrange(0, 1000)}.txt"
                    with open(self.filepath, 'w') as lazyfile:
                        lazyfile.write(self.contents)
                else:
                    assert os.path.isfile(self.filepath)
                return self.filepath

            def __del__(self):
                if self.filepath is not None:
                    os.remove(self.filepath)
        lcf = LazyConcatFile(
            "file '" + "'\nfile '".join(intermediateFilepaths)+"'")
        commandList.append(reduce(list.__add__, [[f"{ffmpegPath}ffmpeg"],
                                                 ['-f', 'concat',
                                                  '-safe', '0',
                                                  '-i', lcf,
                                                  '-c', 'copy',
                                                  '-map', '0'],
                                                 outputMetadataOptions,
                                                 ["-movflags", "faststart", outputFile]]))
        # commandList.append(["echo", "Render complete! Starting cleanup"])
        # commandList.append(["rm", lcf])
        # commandList.extend([["rm", intermediateFile] for intermediateFile in intermediateFilepaths])
        if logLevel >= 3:
            for command in commandList:
                print(command, end='\n')
        return commandList

    if cutMode == 'segment':
        raise Exception("version outdated")
        return filtergraphSegmentVersion()
    elif cutMode == 'trim':
        raise Exception("version outdated")
        return filtergraphTrimVersion()
    elif cutMode == 'chunked':
        return filtergraphChunkedVersion()


def extractInputFiles(ffmpegCommand):
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


def formatCommand(command):
    return ' '.join((quote(str(x)) for x in command))


def saveFiledata(filepath: str):
    with open(filepath, 'wb') as file:
        pickle.dump(allFilesByVideoId, file)
        print("Pickle dump successful")


def loadFiledata(filepath: str):  # suppresses all errors
    try:
        with open(filepath, 'rb') as file:
            print("Starting pickle load...")
            pickleData = pickle.load(file)
            global allFilesByVideoId  # allFilesByVideoId = pickle.load(file)
            allFilesByVideoId = pickleData
            # allFilesByVideoId = {} #string:SourceFile
            global allFilesByStreamer
            allFilesByStreamer = {}  # string:[SourceFile]
            global allStreamersWithVideos
            allStreamersWithVideos = []
            global allStreamerSessions
            allStreamerSessions = {}
            global allScannedFiles
            allScannedFiles = set()
            global filesBySourceVideoPath
            fileBySourceVideoPath = {}
            for file in allFilesByVideoId.values():
                filesBySourceVideoPath[file.videoFile] = file
            for file in sorted(allFilesByVideoId.values(), key=lambda x: x.startTimestamp):
                if file.streamer not in allStreamersWithVideos:
                    allFilesByStreamer[file.streamer] = []
                    allStreamersWithVideos.append(file.streamer)
                scanSessionsFromFile(file)
                allFilesByStreamer[file.streamer].append(file)
                allScannedFiles.add(file.videoFile)
                allScannedFiles.add(file.infoFile)
                if file.chatFile is not None:
                    allScannedFiles.add(file.chatFile)
            print("Pickle load successful")
    except Exception as ex:
        print("Pickle load failed! Exception:", ex)


def calcGameCounts():
    allGames = {}
    for streamer in sorted(allFilesByStreamer.keys()):
        for file in allFilesByStreamer[streamer]:
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
    for streamer in sorted(allFilesByStreamer.keys()):
        for file in allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            for chapter in chapters:
                game = chapter['title']
                length = chapter['end_time'] - chapter['start_time']
                if game not in allGames.keys():
                    allGames[game] = length
                else:
                    allGames[game] += length
    return allGames


def initialize():
    global allFilesByVideoId
    if len(allFilesByVideoId) == 0:
        loadFiledata(DEFAULT_DATA_FILEPATH)
    oldCount = len(allFilesByVideoId)
    scanFiles(log=True)
    if len(allFilesByVideoId) != oldCount:
        saveFiledata(DEFAULT_DATA_FILEPATH)


def reinitialize():
    global allFilesByVideoId
    allFilesByVideoId = {}
    loadFiledata(DEFAULT_DATA_FILEPATH)
    initialize()


def reloadAndSave():
    global allFilesByVideoId
    allFilesByVideoId = {}  # string:SourceFile
    global allFilesByStreamer
    allFilesByStreamer = {}  # string:[SourceFile]
    global allStreamersWithVideos
    allStreamersWithVideos = []
    global allStreamerSessions
    allStreamerSessions = {}
    global allScannedFiles
    allScannedFiles = set()
    global filesBySourceVideoPath
    fileBySourceVideoPath = {}
    scanFiles(log=True)
    saveFiledata(DEFAULT_DATA_FILEPATH)


# %%
# Threading time!
# import types
# import atexit

os.makedirs(logFolder, exist_ok=True)
if COPY_FILES:
    assert localBasepath.strip(' /\\') != basepath.strip(' /\\')


class QueueItem:
    def __init__(self, mainStreamer, fileDate, renderConfig: RenderConfig, outputPath=None):
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
renderStatusLock = threading.Lock()
renderQueue = queue.PriorityQueue()
renderQueueLock = threading.Lock()
if COPY_FILES:
    copyQueue = queue.PriorityQueue()
    copyQueueLock = threading.Lock()
localFileReferenceCounts = {}
localFileRefCountLock = threading.Lock()
MAXIMUM_PRIORITY = 9999
DEFAULT_PRIORITY = 1000
MANUAL_PRIORITY = 500


def incrFileRefCount(filename):
    assert filename.startswith(localBasepath)
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


def decrFileRefCount(filename):
    assert filename.startswith(localBasepath)
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


def setRenderStatus(streamer, date, status):
    assert status in ("RENDERING", "RENDER_QUEUE",
                      "COPY_QUEUE", "COPYING", "FINISHED", "ERRORED")
    assert re.match(r"[\d]{4}-[\d]{2}-[\d]{2}", date)
    assert streamer in allStreamersWithVideos
    key = f"{streamer}|{date}"
    renderStatusLock.acquire()
    oldStatus = renderStatuses[key] if key in renderStatuses.keys() else None
    renderStatuses[key] = status
    if status in ("FINISHED", "ERRORED"):
        with open(statusFilePath, 'wb') as statusFile:
            pickle.dump(renderStatuses, statusFile)
    renderStatusLock.release()
    return oldStatus


def getRenderStatus(streamer, date):
    # print('grs1', date)
    assert re.match(r"[\d]{4}-[\d]{2}-[\d]{2}", date)
    # print('grs2', streamer, allStreamersWithVideos)
    assert streamer in allStreamersWithVideos
    key = f"{streamer}|{date}"
    renderStatusLock.acquire()
    status = renderStatuses[key] if key in renderStatuses.keys() else None
    renderStatusLock.release()
    return status


def deleteRenderStatus(streamer, date, *, lock=True):
    assert re.match(r"[\d]{4}-[\d]{2}-[\d]{2}", date)
    assert streamer in allStreamersWithVideos
    key = f"{streamer}|{date}"
    if lock:
        renderStatusLock.acquire()
    if key in renderStatuses.keys():
        currentStatus = renderStatuses[key]
        if currentStatus in ('RENDER_QUEUE', 'COPY_QUEUE'):
            print(
                f"Cannot delete render status, current value is {currentStatus}")
            if lock:
                renderStatusLock.release()
            return False
        del renderStatuses[key]
        if lock:
            renderStatusLock.release()
        return True
    else:
        print(f"Key {key} not found in render statuses")
        if lock:
            renderStatusLock.release()
        return False


def scanForExistingVideos():
    for file in (f for f in os.listdir(os.path.join(basepath, outputDirectory, "S1")) if f.endswith('.mkv') and not f.endswith('.temp.mkv')):
        fullpath = os.path.join(basepath, outputDirectory, "S1")
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


if COPY_FILES:
    activeCopyTask = None


def copyWorker():
    copyLog = copyText.addLine
    queueEmpty = False
    while True:
        if copyQueue.empty():
            if not queueEmpty:
                print("Copy queue empty, sleeping")
                queueEmpty = True
            ttime.sleep(10)
            continue
            # return
        queueEmpty = False
        copyQueueLock.acquire()  # block if user is editing queue
        priority, task = copyQueue.get(block=False)
        copyQueueLock.release()
        assert getRenderStatus(
            task.mainStreamer, task.fileDate) == 'COPY_QUEUE'
        global activeCopyTask
        activeCopyTask = task
        setRenderStatus(task.mainStreamer, task.fileDate, 'COPYING')
        commandArray = generateTilingCommandMultiSegment(task.mainStreamer,
                                                         task.fileDate,
                                                         task.renderConfig,
                                                         task.outputPath)
        # outputPath = [command for command in commandArray if 'ffmpeg' in command[0]][-1][-1]
        renderCommands = [
            command for command in commandArray if 'ffmpeg' in command[0]]
        allInputFiles = [filepath for command in renderCommands for filepath in extractInputFiles(
            command) if type(filepath) == str and 'anullsrc' not in filepath]
        # print(commandArray)
        allOutputFiles = set([command[-1] for command in renderCommands])
        overallOutputFile = renderCommands[-1][-1]
        sourceFiles = [filesBySourceVideoPath[filepath]
                       for filepath in allInputFiles if filepath not in allOutputFiles]
        # self.intermediateFiles = set([command[-1] for command in commandArray[:-1] if 'ffmpeg' in command[0]])
        # renderCommand = list(task.commandArray)
        for file in sourceFiles:
            remotePath = file.videoFile
            localPath = remotePath.replace(basepath, localBasepath)
            if not os.path.isfile(localPath):
                # ttime.sleep(5)
                copyLog(f"Copying file {remotePath} to local storage")
                # copy to temp file to avoid tripping the if condition with incomplete transfers
                shutil.copyfile(remotePath, localPath+'.temp')
                copyLog('File copy complete, moving to location')
                shutil.move(localPath+'.temp', localPath)
                copyLog('Move complete')
            else:
                copyLog('Local file already exists')
            incrFileRefCount(localPath)
            # copy file and update SourceFile object
            file.localVideoPath = localPath
            # add copied file to filesBySourceVideoPath
            filesBySourceVideoPath[localPath] = file
            # replace file path in renderCommand
            for command in task.commandArray:
                command[command.index(remotePath)] = localPath
        copyLog(
            f'Finished source file copies for render to {overallOutputFile}')
        # item = QueueItem(streamer, day, renderConfig, outPath)
        copyQueue.task_done()
        queueItem = (DEFAULT_PRIORITY, QueueItem(task.mainStreamer,
                     task.fileDate, task.renderConfig, task.outputPath))
        renderQueueLock.acquire()  # block if user is editing queue
        renderQueue.put(queueItem)
        renderQueueLock.release()
        setRenderStatus(task.mainStreamer, task.fileDate, 'RENDER_QUEUE')


activeRenderTask = None
activeRenderTaskSubindex = None
activeRenderSubprocess = None


def renderWorker(stats_period=30,  # 30 seconds between encoding stats printing
                 overwrite_intermediate=DEFAULT_OVERWRITE_INTERMEDIATE,
                 overwrite_output=DEFAULT_OVERWRITE_OUTPUT):
    renderLog = renderText.addLine
    queueEmpty = False
    while True:
        # sessionText, copyText, renderText = bufferedTexts
        if renderQueue.empty():
            if not queueEmpty:
                print("Render queue empty, sleeping")
                queueEmpty = True
            ttime.sleep(10)
            continue
        queueEmpty = False
        renderQueueLock.acquire()  # block if user is editing queue
        priority, task = renderQueue.get(block=False)
        renderQueueLock.release()

        assert getRenderStatus(
            task.mainStreamer, task.fileDate) == 'RENDER_QUEUE'
        global activeRenderTask
        global activeRenderTaskSubindex
        activeRenderTask = task
        taskCommands = generateTilingCommandMultiSegment(task.mainStreamer,
                                                         task.fileDate,
                                                         task.renderConfig,
                                                         task.outputPath)
        renderCommands = [
            command for command in taskCommands if command[0].endswith('ffmpeg')]
        if not overwrite_output:
            outpath = renderCommands[-1][-1]
            count = 1
            suffix = ""
            while os.path.isfile(insertSuffix(outpath, suffix)):
                suffix = f" ({count})"
                count += 1
            renderCommands[-1][-1] = insertSuffix(outpath, suffix)
        finalOutpath = renderCommands[-1][-1]
        # shutil.move(tempOutpath, insertSuffix(outpath, suffix))
        # print(renderCommands)
        # pathSplitIndex = outpath.rindex('.')
        # tempOutpath = outpath[:pathSplitIndex]+'.temp'+outpath[pathSplitIndex:]
        # tempOutpath = insertSuffix(outpath, '.temp')
        # print(outpath, tempOutpath)
        # renderCommands[-1][-1] = tempOutpath # output to temp file, so final filename will always be a complete file
        for i in range(len(renderCommands)):
            renderCommands[i].insert(-1, "-stats_period")
            renderCommands[i].insert(-1, str(stats_period))
            # overwrite (temp) file if it exists
            renderCommands[i].insert(-1, '-y')
        setRenderStatus(task.mainStreamer, task.fileDate, 'RENDERING')
        hasError = False
        gc.collect()
        tempFiles = []
        for i in range(len(taskCommands)):
            activeRenderTaskSubindex = i
            # TODO: add preemptive scheduling
            with open(os.path.join(logFolder, f"{task.mainStreamer}_{task.fileDate}{'' if len(renderCommands)==1 else f'_{i}'}.log"), 'a') as logFile:
                currentCommand = taskCommands[i]
                trueOutpath = None
                if 'ffmpeg' in currentCommand[0]:
                    if not overwrite_intermediate:
                        trueOutpath = currentCommand[-1]
                        if trueOutpath != finalOutpath:
                            assert trueOutpath.startswith(localBasepath)
                            tempFiles.append(trueOutpath)
                        if os.path.isfile(trueOutpath):
                            shouldSkip = True
                            try:
                                videoInfo = getVideoInfo(trueOutpath)
                                duration = int(
                                    float(videoInfo['format']['duration']))
                                # if duration !=
                            except Exception as ex:
                                # if task.renderConfig.logLevel > 0:
                                #    print(ex)
                                renderLog(str(ex))
                            if shouldSkip:
                                # if task.renderConfig.logLevel > 0:
                                renderLog(
                                    f"Skipping render to file {trueOutpath}, file already exists")
                                continue
                        else:
                            currentCommand[-1] = insertSuffix(
                                trueOutpath, '.temp')
                    else:  # overwrite_intermediate
                        currentOutpath = currentCommand[-1]
                        if currentOutpath.startswith(localBasepath):
                            tempFiles.append(currentOutpath)
                    # if task.renderConfig.logLevel > 0:
                    renderLog(
                        f"Running render to file {trueOutpath if trueOutpath is not None else currentCommand[-1]} ...")

                # TODO: figure out how to replace with asyncio processes - need to run from one thread and interrupt from another

                try:
                    process = subprocess.Popen([str(command) for command in currentCommand],
                                               stdin=subprocess.DEVNULL,
                                               stdout=logFile,
                                               stderr=subprocess.STDOUT)
                    activeRenderSubprocess = process
                    returncode = process.wait()
                    activeRenderSubprocess = None
                except KeyboardInterrupt:
                    renderLog(
                        "Keyboard interrupt detected, stopping active render!")
                    process.kill()
                    process.wait()
                    renderLog("Render terminated!")
                    return
                except Exception as ex:
                    renderLog(str(ex))
                    returncode = -1
                    activeRenderSubprocess = None

                if returncode != 0:
                    hasError = True
                    if returncode != 130:  # ctrl-c on UNIX (?)
                        renderLog(
                            f" Render errored! Writing to log file {errorFilePath}")
                        setRenderStatus(task.mainStreamer,
                                        task.fileDate, 'ERRORED')
                        with open(errorFilePath, 'a') as errorFile:
                            errorFile.write(
                                f'Errored on: {formatCommand(currentCommand)}\n')
                            errorFile.write(f'Full command list: ')
                            errorFile.write(' ;; '.join(
                                (formatCommand(renderCommand) for renderCommand in renderCommands)))
                            errorFile.write('\n\n')
                    break
                else:
                    if trueOutpath is not None:
                        shutil.move(currentCommand[-1], trueOutpath)
                        renderLog(f" Render to {trueOutpath} complete!")
                    else:
                        renderLog(f" Render to {currentCommand[-1]} complete!")
        if not hasError:
            print("Render task finished, cleaning up temp files:")
            print(tempFiles)
            setRenderStatus(task.mainStreamer, task.fileDate, 'FINISHED')
            if COPY_FILES:
                for file in (f for f in task.sourceFiles if f.videoFile.startswith(localBasepath)):
                    remainingRefs = decrFileRefCount(file.localVideoPath)
                    if remainingRefs == 0:
                        renderLog(f"Removing local file {file}")
                        os.remove(file)
            # intermediateFiles = set([command[-1] for command in renderCommands[:-1] if command[0].endswith('ffmpeg')])
            # for file in intermediateFiles:
            for file in tempFiles:
                renderLog(f"Removing intermediate file {file}")
                assert basepath not in file
                os.remove(file)
        renderQueue.task_done()
        if __debug__:
            break


def getAllStreamingDaysByStreamer():
    daysByStreamer = {}
    for streamer in sorted(allFilesByStreamer.keys()):
        days = set()
        for file in allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            fileStartTimestamp = file.startTimestamp
            for chapter in chapters:
                startTime = datetime.fromtimestamp(
                    fileStartTimestamp+chapter['start_time'], LOCAL_TIMEZONE)
                startDate = datetime.strftime(startTime, "%Y-%m-%d")
                days.add(startDate)
                # endTime = datetime.fromtimestamp(fileStartTimestamp+chapter['end_time'], LOCAL_TIMEZONE)
                # endDate = datetime.strftime(endTime, "%Y-%m-%d")
                # days.add(endDate)
        daysByStreamer[streamer] = list(days)
        daysByStreamer[streamer].sort(reverse=True)
    return daysByStreamer

# drawLabels=False, startTimeMode='mainSessionStart', endTimeMode='mainSessionEnd', logLevel=2, #max logLevel = 4
# sessionTrimLookback=1, #sessionTrimLookahead=-1, minGapSize=0, outputCodec='libx264',
# encodingSpeedPreset='medium', useHardwareAcceleration=0, #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale, bit 3(4)=(unsupported) encode
# maxHwaccelFiles=0, minimumTimeInVideo=900, cutMode='chunked', useChat=True, ffmpegPath=''


def sessionWorker(monitorStreamers=DEFAULT_MONITOR_STREAMERS,
                  maxLookback: timedelta = DEFAULT_MAX_LOOKBACK,
                  dataFilepath=DEFAULT_DATA_FILEPATH,
                  renderConfig=RenderConfig()):
    # drawLabels=False,
    # startTimeMode='mainSessionStart',
    # endTimeMode='mainSessionEnd',
    # logLevel=0,
    # sessionTrimLookback=1,
    # sessionTrimLookahead=3,
    # minimumTimeInVideo=1200,
    # minGapSize=900)):
    sessionLog = sessionText.addLine
    global allFilesByVideoId
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
        if __debug__ or timeSinceLastDownload > minimumSessionWorkerDelay:
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
                        item = QueueItem(streamer, day, renderConfig, outPath)
                        sessionLog(
                            f"Adding render for streamer {streamer} from {day}")
                        (copyQueue if COPY_FILES else renderQueue).put(
                            (DEFAULT_PRIORITY, item))
                        setRenderStatus(
                            streamer, day, "COPY_QUEUE" if COPY_FILES else "RENDER_QUEUE")
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


# %%
class Command:
    def __init__(self, targetFunc, description):
        self.targetFunc = targetFunc
        self.description = description


commandArray = []


def endRendersAndExit():
    print('Shutting down, please wait at least 15 seconds before manually killing...')
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if activeRenderSubprocess is not None:
        print("Terminating render thread")
        activeRenderSubprocess.terminate()
        activeRenderSubprocess.wait(10)
        if activeRenderSubprocess.poll is None:
            print(
                "Terminating render thread did not complete within 10 seconds, killing instead")
            activeRenderSubprocess.kill()
            activeRenderSubprocess.wait()
        if activeRenderSubprocess.poll is not None:
            print("Active render stopped successfully")
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    print("Stopping!")
    sys.exit(0)


commandArray.append(Command(endRendersAndExit, 'Exit program'))


def startRenderThread():
    print("Starting render thread")
    if renderThread is not None and not renderThread.is_alive():
        renderThread.start()
    index = None
    for i in range(len(commandArray)):
        if commandArray[i].targetFunc == startRenderThread:
            index = i
            break
    assert index is not None
    del commandArray[index]


commandArray.append(Command(startRenderThread, 'Start render thread'))


def printActiveJobs():
    print(f"Active render job:",
          "None" if activeRenderTask is None else f"{str(activeRenderTask)}, subindex {str(activeRenderTaskSubindex)}\n{activeRenderTask.__repr__()}")
    if COPY_FILES:
        print(f"Active copy job:",
              "None" if activeCopyTask is None else f"{str(activeCopyTask)}")


commandArray.append(Command(printActiveJobs, 'Print active jobs'))


def printQueuedJobs():
    if len(renderQueue.queue) == 0:
        print("Render queue: empty")
    else:
        for queueItem in sorted(renderQueue.queue):
            print(queueItem)
    if COPY_FILES:
        if len(copyQueue.queue) == 0:
            print("Copy queue: empty")
        else:
            for queueItem in sorted(copyQueue.queue):
                print(queueItem)


commandArray.append(Command(printQueuedJobs, 'Print queued jobs'))


def printJobsWithStatus(status):
    renderStatusLock.acquire()
    selectedRenders = [key.split(
        '|') for key in renderStatuses.keys() if renderStatuses[key] == status]
    renderStatusLock.release()
    streamersWithSelected = sorted(
        set([render[0] for render in selectedRenders]))
    # print(streamersWithSelected)
    selectedStreamer = None
    if len(streamersWithSelected) > 1:
        print("Select streamer (blank for all):")
        for i in range(len(streamersWithSelected)):
            streamer = streamersWithSelected[i]
            count = len(
                [render for render in selectedRenders if render[0] == streamer])
            print(f"{i+1}: {streamer} ({count} renders)")
        userInput = input(" >> ")
        try:
            selectedStreamer = streamersWithSelected[int(userInput)-1]
        except:
            selectedStreamer = None
    formattedStatus = status[0].upper()+status[1:].lower()
    print(f"{formattedStatus} renders:")
    print(f"Streamer                  | File date")
    for streamer, date in sorted(selectedRenders):
        if selectedStreamer is None or streamer == selectedStreamer:
            print(f"{streamer:25} | {date}")


commandArray.append(
    Command(partial(printJobsWithStatus, 'FINISHED'), 'Print completed jobs'))
commandArray.append(
    Command(partial(printJobsWithStatus, 'ERRORED'), 'Print errored jobs'))


def clearErroredJobs():
    renderStatusLock.acquire()
    selectedRenders = [key.split('|') for key in renderStatuses.keys(
    ) if renderStatuses[key] == 'ERRORED']
    streamersWithSelected = sorted(
        set([render[0] for render in selectedRenders]))
    # print(streamersWithSelected)
    selectedStreamer = None
    if len(streamersWithSelected) > 1:
        print("Select streamer (blank for all, 'q' to cancel):")
        for i in range(len(streamersWithSelected)):
            streamer = streamersWithSelected[i]
            count = len(
                [render for render in selectedRenders if render[0] == streamer])
            print(f"{i+1}: {streamer} ({count} errored jobs)")
        userInput = input(" >> ")
        if len(userInput) > 0:
            if userInput.lower() in quitOptions:
                return
            try:
                selectedStreamer = streamersWithSelected[int(userInput)-1]
            except:
                selectedStreamer = None
    for streamer, date in selectedRenders:
        if selectedStreamer is None or streamer == selectedStreamer:
            print(f"Clearing error status for {streamer} {date}")
            deleteRenderStatus(streamer, date, lock=False)
    with open(statusFilePath, 'wb') as statusFile:
        pickle.dump(renderStatuses, statusFile)
    renderStatusLock.release()


commandArray.append(Command(clearErroredJobs, 'Clean up errored jobs'))

quitOptions = ('quit', 'exit', 'q')

# ... = done
# None = cancel/quit


def readStreamer(allStreamersList=None, inputText="Enter streamer name, or 'list' to list valid names. 'q' to exit/cancel: "):
    # print(allStreamersWithVideos)
    if allStreamersList is None:
        allStreamersList = allStreamersWithVideos
    print("Available streamers:", allStreamersList)
    while True:
        print(inputText)
        userInput = input(" >> ")
        if userInput == '':
            return ...
        elif userInput.lower() in quitOptions:
            return None
        elif userInput.lower() == 'list':
            for streamer in allStreamersList:
                print(streamer)
            continue
        for streamer in allStreamersList:
            if streamer.lower() == userInput.lower():
                return streamer
        closestMatch, ratio = fuzzproc.extractOne(userInput, allStreamersList)
        if ratio < 50:
            print("Could not parse streamer name, please try again")
            if requireVideos:
                print(
                    "(If the streamer name is valid, they may not have any known videos)")
            continue
        isMatch = input(
            f"Streamer '{userInput}' not found, did you mean '{closestMatch}'? ({str(ratio)}% match) (y/n) ")
        if isMatch.lower().startswith('y'):
            return closestMatch


def readExcludeStreamers():  # TODO: rename to be more generic
    print("Selecting streamers to exclude, or empty input when done entering")
    streamerExclusions = {}
    while True:
        parsedStreamer = readStreamer(
            inputText="Enter streamer name, or 'list' to list valid names. 'q' to exit/cancel. Leave empty if done: ")
        if parsedStreamer is None:
            return None
        elif parsedStreamer == ...:
            if len(streamerExclusions) == 0:
                print("No streamers entered, cancelling")
                return None
            else:
                break
        allGames = sorted(
            ((game, count) for game, count in calcGameCounts().items()), key=lambda x: -x[1])
        print(f"Streamer {parsedStreamer} selected")
        excludedGames = []

        def readExcludeGame():
            gamesPage = 0
            gamesPageSize = 20
            while True:
                startIndex = gamesPage*gamesPageSize
                endIndex = (gamesPage+1)*gamesPageSize
                pageGames = allGames[startIndex:endIndex]
                hasPrevPage = gamesPage > 0
                hasNextPage = endIndex < len(allGames)
                if hasPrevPage:
                    print("P) Previous page")
                for i in range(len(pageGames)):
                    print(f"{i+1}) {pageGames[i][0]}")
                if hasNextPage:
                    print("N) Next page")
                userInput = input(" >> ")
                if userInput.lower() in quitOptions:
                    return None
                elif userInput.lower() == 'p':
                    if hasPrevPage:
                        gamesPage -= 1
                        continue
                    else:
                        print("No previous page")
                elif userInput.lower() == 'n':
                    if hasNextPage:
                        gamesPage += 1
                        continue
                    else:
                        print("No next page")
                elif userInput == '':
                    return ...
                elif userInput.isdigit():
                    index = int(userInput)-1
                    if not 0 < index <= len(pageGames):
                        print(
                            f"Entered number outside of valid range (1-{len(pageGames)})")
                        continue
                    return pageGames[index][0]
                else:
                    for game, _ in allGames:
                        if game.lower() == userInput.lower():
                            return excludeGame
        while True:
            if len(excludedGames) > 0:
                print(f"Excluded games so far: {str(excludedGames)}")
                print(
                    f"Enter game number or manually enter game name. Leave blank to end game selection or 'q' to abort:")
            else:
                print(
                    f"Enter game number or manually enter game name. Leave blank to select all games or 'q' to abort:")
            excludeGame = readExcludeGame()
            if excludeGame is None:
                return None
            elif excludeGame == ...:
                break
            else:
                excludedGames.append(excludeGame)
        if len(excludedGames) == 0:
            streamerExclusions[parsedStreamer] = None
        else:
            streamerExclusions[parsedStreamer] = excludedGames
    return streamerExclusions


renderConfigSchemaManualHandles = {'excludeStreamers': readExcludeStreamers,
                                   'includeStreamers': readExcludeStreamers}


def readRenderConfig(initialRenderConfig=None):
    renderConfig = initialRenderConfig
    if renderConfig is None:
        renderConfig = RenderConfig()
    print(renderConfig.__dict__)
    print(len(renderConfig.__dict__.keys()))
    while True:  # manually break out
        configDict = renderConfig.__dict__
        print("Current render settings:")
        sortedKeys = sorted(configDict.keys())
        for i in range(len(sortedKeys)):
            print(f"{i+1}) {sortedKeys[i]} = {str(configDict[sortedKeys[i]])}")
        print("F) Finish and queue render")
        userInput = input(" >> ")
        if userInput in quitOptions:
            return None
        elif userInput.lower() == 'f':
            return renderConfig
        try:
            selectedKey = sortedKeys[int(userInput)-1]
        except:
            print(f"Invalid selection: '{userInput}'")
            continue
        if selectedKey in renderConfigSchemaManualHandles.keys():
            newValue = renderConfigSchemaManualHandles[selectedKey]()
        else:
            print(f"New value for {selectedKey}: ")
            newValue = input(" >> ")
        configDict[selectedKey] = newValue


def inputManualJob(initialRenderConfig=None):
    allStreamerDays = getAllStreamingDaysByStreamer()
    mainStreamer = readStreamer(allStreamerDays.keys())
    if mainStreamer is None or mainStreamer == ...:
        return
    fileDate = None
    streamerDays = allStreamerDays[mainStreamer]
    if len(streamerDays) == 0:
        print("Selected streamer has no streams!")
        return
    pageNum = 0
    pageSize = 30
    pageWidth = 3
    while fileDate is None:
        print("Enter file date to render:")
        optionRows = []
        hasPrevPage = pageNum > 0
        if hasPrevPage:
            print("P) Previous page")
        startIndex = pageNum*pageSize
        endIndex = (pageNum+1)*pageSize
        dates = streamerDays[startIndex:endIndex]
        for dayIndex in range(len(dates)):
            print(f"{dayIndex+1}) {dates[dayIndex]}    ", end='')
            if dayIndex % pageWidth == pageWidth-1 or dayIndex == len(dates)-1:
                print()
        hasNextPage = endIndex < len(streamerDays)
        if hasNextPage:
            print("N) Next page")
        userInput = input(" >> ")
        if userInput.lower() == 'p':
            if hasPrevPage:
                pageNum -= 1
                continue
            else:
                print("No previous page!")
        elif userInput.lower() == 'n':
            if hasNextPage:
                pageNum += 1
                continue
            else:
                print("No next page!")
        elif userInput.lower() in quitOptions:
            return
        try:
            fileDate = dates[int(userInput)-1]
        except:
            print("Invalid input!")
            ttime.sleep(2)
            fileDate = None
    currentStatus = getRenderStatus(mainStreamer, fileDate)
    print(f"Got {mainStreamer} {fileDate}, current status {currentStatus}")

    outputPath = input("Enter output path (Leave blank for default):\n")
    if outputPath == '':
        outputPath = getVideoOutputPath(mainStreamer, fileDate)

    if currentStatus == 'RENDER_QUEUE':
        raise Exception("Editing queued renders not supported yet")
    renderConfig = readRenderConfig()
    if renderConfig is None:
        return None
    item = QueueItem(mainStreamer, fileDate, renderConfig, outputPath)
    print(f"Adding render for streamer {mainStreamer} from {fileDate}")
    setRenderStatus(mainStreamer, fileDate,
                    'COPY_QUEUE' if COPY_FILES else 'RENDER_QUEUE')
    (copyQueue if COPY_FILES else renderQueue).put((MANUAL_PRIORITY, item))


commandArray.append(Command(inputManualJob, 'Add new manual job'))


def editQueueItem(queueEntry):
    priority, item = queueEntry
    mainStreamer = item.mainStreamer
    fileDate = item.fileDate
    renderConfig = item.renderConfig
    outputPath = item.outputPath
    while True:
        print("Current values:")
        print(f"Render config: {str(renderConfig)}")
        print(f"Priority: {priority}")
        print(f"Output path: {outputPath}")
        print("Select option:")
        print("R) Render configuration\nP) Priority\nO) Output path\nD) Delete item from queue\nF) Finish editing and re-add to queue")
        userInput = input(" >> ")
        if userInput.lower() in quitOptions:
            return None
        elif userInput.lower() == 'r':
            renderConfig = readRenderConfig(renderConfig)
        elif userInput.lower() == 'p':
            valueInput = input(
                f"Enter new priority (0-{MAXIMUM_PRIORITY}, default is {DEFAULT_PRIORITY}):  ")
            try:
                value = int(valueInput)
                if not 0 <= value <= MAXIMUM_PRIORITY:
                    print("Value outside of valid range!")
                    continue
                priority = value
            except:
                print(
                    f"Unable to parse priority '{valueInput}'! Must be a positive integer")
                continue
        elif userInput.lower() == 'o':
            print(
                f"Enter new output path (relative to {basepath}), blank to cancel:")
            valueInput = input(basepath)
            if len(valueInput) == 0:
                continue
            elif valueInput.lower() in quitOptions:
                return None
            elif not any((valueInput.endswith(ext) for ext in videoExts)):
                print(
                    f"Output path must be that of a video file - must end with one of: {', '.join(videoExts)}")
                continue
            else:
                outputPath = os.path.join(basepath, valueInput)
        elif userInput.lower() == 'f':
            break
        elif userInput.lower() == 'd':
            deleteRenderStatus(mainStreamer, fileDate)
            return ...
        else:
            print(f"Invalid option: '{userInput}'")
    newItem = QueueItem(mainStreamer, fileDate, renderConfig, outputPath)
    return (priority, newItem)


def editQueue():
    selectedQueue = None
    selectedQueueLock = None
    if COPY_FILES:
        print("Select queue:\nR) Render queue\nC) Copy queue")
        while selectedQueue is None:
            userInput = input(" >> ")
            if userInput.lower().startswith('r'):
                selectedQueue = renderQueue
                selectedQueueLock = renderQueueLock
            elif userInput.lower().startswith('c'):
                selectedQueue = copyQueue
                selectedQueueLock = copyQueueLock
            elif userInput.lower() in quitOptions:
                return
            else:
                print(f"Unrecognized input ('q' to quit): '{userInput}'")
    else:
        selectedQueue = renderQueue
        selectedQueueLock = renderQueueLock
    selectedQueueLock.acquire()
    items = []
    while not selectedQueue.empty():
        items.append(selectedQueue.get())
    while True:
        if len(items) == 0:
            print("Queue is empty!")
            selectedQueueLock.release()
            return
        print("Select queue item to edit: ")
        for i in range(len(items)):
            priority, queueItem = items[i]
            mainStreamer = queueItem.mainStreamer
            fileDate = queueItem.fileDate
            print(f"{i+1}) {mainStreamer} {fileDate} (priority: {priority})")
        userInput = input(" >> ")
        if len(userInput) == 0 or userInput.lower() in quitOptions:
            break
        try:
            index = int(userInput)-1
            selectedItem = items[index]
            modifiedItem = editQueueItem(selectedItem)
            if modifiedItem is None:
                break
            elif modifiedItem == ...:
                del items[index]
            else:
                items[index] = modifiedItem
                items.sort()
        except:
            print(f"Invalid input: '{userInput}'")
            continue
    for item in items:  # push modified items back into queue with their new priorities
        selectedQueue.put(item)
    selectedQueueLock.release()


commandArray.append(Command(editQueue, 'Edit queue(s)'))


def commandWorker():
    while True:
        for _ in range(5):
            print()
        for i in range(len(commandArray)):
            command = commandArray[i]
            print(f"{str(i)}. {command.description}")
        # print("\n\n\n\n\n\n0. Exit program\n1. Print active jobs\n2. Print queued jobs\n3. Manually add job\n4. Modify/rerun job\n")
        userInput = input(" >> ")
        if __debug__ and userInput.lower() in quitOptions:
            return
        if not userInput.isdigit():
            print(f"Invalid input: '{userInput}'")
            print("Please try again")
            continue
        optionNum = int(userInput)
        if optionNum < 0 or optionNum > len(commandArray):
            print(f"Invalid option number: {userInput}")
            print("Please try again")
        try:
            commandArray[optionNum].targetFunc()
        except KeyboardInterrupt as ki:
            print(
                "Detected keyboard interrupt, returning to main menu. Press Ctrl-C again to exit program")
        # raise Exception("Not implemented yet")


# %%
# import time as ttime
START_TIME = ttime.time()

# Function to exit the program


def exit_program(button):
    raise urwid.ExitMainLoop()

# Text Widgets


class BufferedText(urwid.Text):
    def __init__(self, buffer_length=100, label='', *, wrap='any'):
        super().__init__("", align='left', wrap=wrap)
        self.buffer = []
        self.buffer_length = buffer_length
        self.label = label
        self.lock = threading.Lock()

    def addLine(self, line):  # function will likely be called by a different thread than the main thread that created it
        if not URWID:
            if len(self.buffer) > 0:  # clear buffer in case of race conditions with URWID
                for b in self.buffer:
                    print(b)
                self.buffer = []
            print(line)
            return
        self.lock.acquire()
        try:
            while len(self.buffer) >= self.buffer_length:
                del self.buffer[-1]
            formatted_line = f'[{self.label}{ttime.time()-START_TIME}] {line}'
            self.buffer.insert(0, formatted_line)
            self.set_text('\n'.join(self.buffer))
            global mainloopMessageBus
            # mainloopMessageBus.write(1)
            os.write(mainloopMessageBus, self.label.encode('utf-8'))
        finally:
            self.lock.release()


btLabels = ['S', 'R']
if COPY_FILES:
    btLabels.insert(1, 'C')
bufferedTexts = [BufferedText(label=label) for label in btLabels]

if COPY_FILES:
    sessionText, copyText, renderText = bufferedTexts
else:
    sessionText, renderText = bufferedTexts

# Pile for Text Widgets
btFillers = [urwid.Filler(bt, 'top') for bt in bufferedTexts]

# Columns for Text Widgets
# columns = urwid.Columns([left_filler, right_filler])
columns = urwid.Columns(btFillers)

divider = urwid.Divider('=')

# Main Loop


def testfunction1(sleeptime, buftext):
    for i in range(50):
        ttime.sleep(sleeptime)
        buftext.addLine(f'Blah blah blah {i}')


class MenuButton(urwid.Button):
    def __init__(self, caption, callback):
        super().__init__("Urwid integration is still in active development")
        urwid.connect_signal(self, 'click', callback)
        self._w = urwid.AttrMap(urwid.SelectableIcon(
            ['  \N{BULLET} ', caption], 2), None, 'selected')


class SubMenu(urwid.WidgetWrap):
    def __init__(self, caption, choices):
        super().__init__(MenuButton(
            [caption, "\N{HORIZONTAL ELLIPSIS}"], self.open_menu))
        line = urwid.Divider('\N{LOWER ONE QUARTER BLOCK}')
        listbox = urwid.Pile(urwid.SimpleFocusListWalker([
            urwid.AttrMap(urwid.Text(["\n  ", caption]), 'heading'),
            urwid.AttrMap(line, 'line'),
            urwid.Divider()] + choices + [ActionChoice('Close menu', closeTopBox),
                                          urwid.Divider()]))
        self.menu = urwid.AttrMap(listbox, 'options')

    def open_menu(self, button):
        top.open_box(self.menu)


class PagedMenu(urwid.WidgetWrap):
    def __init__(self, caption, choices, pageHeight=10, pageWidth=3, *args, **kwargs):
        super().__init__(MenuButton(
            [caption, "\N{HORIZONTAL ELLIPSIS}"], self.open_menu))
        self.menu = None
        self.listbox = None
        self.line = urwid.Divider('\N{LOWER ONE QUARTER BLOCK}')
        self.nextPageOption = MenuButton('Next page', self.next_page)
        self.prevPageOption = MenuButton('Previous page', self.prev_page)
        self.choices = choices
        self.pageNum = 0
        self.pageWidth = pageWidth
        self.pageHeight = pageHeight
        self.pageSize = pageWidth * pageHeight
        self.args = args
        self.kwargs = kwargs

    def _get_current_page(self):
        if callable(self.choices):
            options = self.choices(*self.args, **self.kwargs)
        else:
            options = self.choices
        page = options[self.pageNum *
                       self.pageSize: (self.pageNum+1)*self.pageSize]
        return page

    def open_menu(self, button):
        currentPage = self._get_current_page()
        self.listbox = urwid.Pile(urwid.SimpleFocusListWalker([
            urwid.AttrMap(urwid.Text(["\n  ", self.caption]), 'heading'),
            urwid.AttrMap(self.line, 'line'),
            urwid.Divider()] + currentPage + [ActionChoice('Close menu', closeTopBox),
                                              urwid.Divider()]))
        self.menu = urwid.AttrMap(self.listbox, 'options')
        top.open_box(self.menu)

    def next_page(self):
        self.pageNum += 1
        top.close_box()
        self.open_menu(None)
        # top.open_box(self.menu)

    def prev_page(self):
        self.pageNum -= 1
        top.close_box()
        self.open_menu(None)
        # top.open_box(self.menu)


class InfoChoice(urwid.WidgetWrap):
    def __init__(self, caption, callback, text):
        super().__init__(
            MenuButton(caption, self.item_chosen))
        self.caption = caption
        self.callback = callback
        self.text = text

    def item_chosen(self, button):
        if type(self.text) == str:
            message = self.text
        elif type(self.text) == bytes:
            message = self.text.decode()
        elif callable(self.text):
            message = self.text()
        else:
            message = str(self.text)
        # response = urwid.Text(['  You chose ', self.caption, '\n'])
        response = urwid.Text(message+'\n')
        done = MenuButton('Ok', self.callback)
        response_box = urwid.Pile([response, done])
        top.open_box(urwid.AttrMap(response_box, 'options'))


class ActionChoice(urwid.WidgetWrap):
    def __init__(self, caption, callback):
        super().__init__(
            MenuButton(caption, self.item_chosen))
        self.caption = caption
        self.callback = callback

    def item_chosen(self, button):
        self.callback(button)
        # response = urwid.Text(['  You chose ', self.caption, '\n'])
        # done = MenuButton('Ok', self.callback)
        # response_box = urwid.Pile([response, done])
        # top.open_box(urwid.AttrMap(response_box, 'options'))


def exit_program(key):
    raise urwid.ExitMainLoop()


def closeTopBox(button):
    top.close_box()


def renderThreadChoice(key):
    if renderThread.nativeId is None:
        renderThread.start()


class RenderThreadStatusString:
    def __str__(self):
        started = renderThread.nativeId is not None
        return 'Render thread already started!' if started else 'Starting render thread!'


menu_top = SubMenu('Main Menu', [
    # SubMenu('Applications', [
    #    SubMenu('Accessories', [
    #        InfoChoice('Text Editor', closeTopBox, 'Text Editor'),
    #        InfoChoice('Terminal', closeTopBox, 'testFunc1'),
    #        ActionChoice('Close menu', closeTopBox)
    #    ]),
    #    ActionChoice('Close menu', closeTopBox)
    # ]),
    # SubMenu('System', [
    #    SubMenu('Preferences', [
    #        InfoChoice('Appearance', closeTopBox, 'Appearance'),
    #        ActionChoice('Close menu', closeTopBox)
    #    ]),
    #    InfoChoice('Lock Screen', exit_program, 'Lock Screen'.encode()),
    #    ActionChoice('Close menu', closeTopBox)
    # ]),
    ActionChoice('Exit program', endRendersAndExit if 'endRendersAndExit' in globals(
    ).keys() else exit_program),
    InfoChoice('Start render thread', renderThreadChoice,
               RenderThreadStatusString()),
    # InfoChoice('Print active jobs', activeJobsChoice, ),
    # InfoChoice('Print queued jobs'),
    # InfoChoice('Print completed jobs'),
    # InfoChoice('Print errored jobs'),
    # ActionChoice('Clean up errored jobs'),
    # PagedMenu('Edit queue(s)')
    # InfoChoice('')
])

palette = [
    (None,  'light gray', 'black'),
    ('heading', 'black', 'light gray'),
    ('line', 'black', 'light gray'),
    ('options', 'dark gray', 'black'),
    ('focus heading', 'white', 'dark red'),
    ('focus line', 'black', 'dark red'),
    ('focus options', 'black', 'light gray'),
    ('selected', 'white', 'dark blue')]
focus_map = {
    'heading': 'focus heading',
    'options': 'focus options',
    'line': 'focus line'}


class HorizontalBoxes(urwid.Columns):
    def __init__(self):
        super().__init__([], dividechars=1)

    def open_box(self, box):
        if self.contents:
            del self.contents[self.focus_position + 1:]
        self.contents.append((urwid.AttrMap(box, 'options', focus_map),
                              self.options('given', 24)))
        self.focus_position = len(self.contents) - 1

    def close_box(self):
        if self.contents:
            del self.contents[self.focus_position:]
        self.focus_position = len(self.contents) - 1


top = HorizontalBoxes()

top.open_box(menu_top.menu)

vbox = urwid.Pile([columns, ('pack', divider), ('pack', top)])

# %%

URWID = ENABLE_URWID


def mainStart():
    # urwid.MainLoop(urwid.Filler(top, 'middle', 10), palette).run()
    mainloop = urwid.MainLoop(vbox, palette)

    def messageBusReceiverV1(data: bytes):
        # use first byte to look up label, then parse rest as data
        raise Exception('not implemented')
        return True

    def messageBusReceiverV2(data: bytes):
        # ignore data, simply use it as a callback to trigger draw_screen()
        mainloop.draw_screen()

    global mainloopMessageBus
    mainloopMessageBus = mainloop.watch_pipe(messageBusReceiverV2)
    global URWID
    if ENABLE_URWID:
        try:
            mainloop.run()
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


# %%
renderThread = threading.Thread(target=renderWorker)
renderThread.daemon = True
if COPY_FILES:
    copyThread = threading.Thread(target=copyWorker)
    copyThread.daemon = True


if __name__ == '__main__':
    defaultSessionRenderConfig = RenderConfig()  # drawLabels=False,
    # startTimeMode='mainSessionStart',
    # endTimeMode='mainSessionEnd',
    # logLevel=0,
    # sessionTrimLookback=0,
    # sessionTrimLookahead=4)
    # initialize()
    if not __debug__:
        print("Deployment mode")
        if COPY_FILES:
            copyThread.start()
        # renderThread.start()
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
        print(allStreamersWithVideos)
        # copyWorker()
        # print(getAllStreamingDaysByStreamer()['ChilledChaos'])
        # commandWorker()
        mainStart()
        allGames = calcGameCounts()
        for game in sorted(allGames.keys(), key=lambda x: (allGames[x], x)):
            print(game, allGames[game])
        del allGames


# %%

def normalizeAllGames():
    gameCounts = calcGameCounts()
    pprint(gameCounts)
    print("\n\n\n---------------------------------------------------------------\n\n\n")
    knownReplacements = {}
    lowercaseGames = {}
    for game, alias in gameAliases.items():
        assert game.lower() not in lowercaseGames.keys()
        knownReplacements[game] = list(alias)
        lowercaseGames[game.lower()] = game
    replacedGames = {}
    for game in gameCounts.keys():
        # if gameCounts[game] == 1:
        #    continue
        trueGame = None
        for key in knownReplacements.keys():
            if any((game == alias for alias in knownReplacements[key])):
                trueGame = key
                break
        if trueGame is None:
            trueGame = game
        else:
            print("game, trueGame:", game, trueGame)
            replacedGames[game] = trueGame
            continue

        # if any((any((game == alias for alias in knownReplacements[key])) for key in knownReplacements.keys())):
            # game is already a known alias
        #    continue
        lowergame = game.lower()
        if lowergame in lowercaseGames.keys():
            altgame = lowercaseGames[lowergame]
            if altgame == game:
                continue
            if gameCounts[game] > gameCounts[altgame]:
                aliases = knownReplacements[altgame]
                aliases.append(altgame)
                del knownReplacements[altgame]
                knownReplacements[game] = aliases
            elif gameCounts[altgame] > gameCounts[game]:
                knownReplacements[altgame].append(game)
            else:
                raise Exception(
                    f"Two capitalizations have the same count, cannot determine which is correct: {game}; {altgame}")
        # else:
        elif gameCounts[game] > 1:
            knownReplacements[game] = []
            lowercaseGames[lowergame] = game
    print("\n\n\n---------------------------------------------------------------\n\n\nreplacedGames:")
    pprint(replacedGames, width=200)
    print("\n\n\n---------------------------------------------------------------\n\n\nknownReplacements:")
    pprint(knownReplacements, width=200)
    print("\n\n\n---------------------------------------------------------------\n\n\n")
    for game in (game for game in gameCounts.keys() if gameCounts[game] == 1):
        matches = []
        lowergame = game.lower()
        lowergameParts = lowergame.split(' ')
        for knownGame, knownAliases in knownReplacements.items():
            knownGameLower = knownGame.lower()
            knownGameParts = knownGameLower.split(' ')
            if all((part in lowergameParts for part in knownGameParts)) and knownGameLower in lowergame:
                difference = lowergame.replace(knownGameLower, '').strip()
                if not difference.isdigit():
                    matches.append(knownGame)
                    continue
            for knownAlias in knownAliases:
                aliasLower = knownAlias.lower()
                aliasParts = aliasLower.split(' ')
                if all((part in lowergameParts for part in aliasParts)) and aliasLower in lowergame:
                    difference = lowergame.replace(aliasLower, '').strip()
                    if not difference.isdigit():
                        matches.append(knownGame)
        if len(matches) > 0:
            print("game, matches:", game, matches)
            # longestIndex = 0
            # for index in range(1, len(matches)):
            #    if len(matches[index]) > len(matches[longestIndex])
            #        longestIndex = index

            def locateIndex(x):
                index = game.lower().find(x.lower())
                if index != -1:
                    return index
                if x in knownReplacements.keys():
                    for alias in knownReplacements[x]:
                        index = alias.lower().find(x.lower())
                        if index != -1:
                            return index
                return -1
            longestMatch = sorted(matches, key=lambda x: (
                0-locateIndex(x), len(x)))[-1]
            # longestMatch = sorted(matches, key=lambda x:(game.lower().index(x.lower()), len(x)))[-1]
            # assert len(matches) == 1
            knownReplacements[longestMatch].append(game)
    for key in list(knownReplacements.keys()):
        if len(knownReplacements[key]) == 0:
            del knownReplacements[key]
    print("\n\n\n---------------------------------------------------------------\n\n\nknownReplacements:")
    pprint(knownReplacements, width=200)

    def normalizeGame(originalGame: str):
        for game, aliases in knownReplacements.items():
            if originalGame == game or originalGame in aliases:
                return game
    # for streamer, sessions in allStreamerSessions.items():
    #    print(f"Normalizing games for streamer {streamer}")
        # for session in sessions:
        #    ...

# pprint(sorted(calcGameTimes().items(), key=lambda x:x[1]))
# normalizeAllGames()


# %%

def normalizeAllGamesV2():
    gameCounts = calcGameCounts()
    pprint(gameCounts)
    print("\n\n\n---------------------------------------------------------------\n\n\n")
    replacements = {}

# %%
