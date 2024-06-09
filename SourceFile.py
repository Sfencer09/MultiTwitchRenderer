from datetime import datetime
import os
import pickle
import re
import subprocess
import json
from typing import Dict, List, Set
import scanned

from MTRConfig import getConfig

from Session import Session
from ParsedChat import ParsedChat, convertToDatetime

from MTRLogging import getLogger
logger = getLogger('SourceFile')

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


def scanSessionsFromFile(file: 'SourceFile'):
    streamer = file.streamer
    if streamer not in scanned.allStreamerSessions.keys():
        scanned.allStreamerSessions[streamer] = []
    chapters = file.infoJson['chapters']
    startTime = file.startTimestamp
    for chapter in chapters:
        game = chapter['title']
        chapterStart = startTime + chapter['start_time']
        chapterEnd = startTime + chapter['end_time']
        session = Session(file, game, chapterStart, chapterEnd)
        scanned.allStreamerSessions[streamer].append(session)


def trimInfoDict(infoDict: dict):
    newDict = dict(infoDict)
    if 'thumbnails' in newDict:
        del newDict['thumbnails']
    if 'formats' in newDict:
        del newDict['formats']
    if 'subtitles' in newDict:
        del newDict['subtitles']
    if 'http_headers' in newDict:
        del newDict['http_headers']
    return newDict

class SourceFile:
    duration:int
    startTimestamp:int
    endTimestamp:int
    downloadTime:datetime
    
    def __init__(self, streamer: str, videoId: str, *, videoFile=None, infoFile=None, chatFile=None):
        assert videoFile is None or os.path.isabs(videoFile)
        assert infoFile is None or os.path.isabs(infoFile)
        self.streamer:str = streamer
        self.videoId:str = videoId
        self.videoFile:str = None
        if videoFile is not None:
            self.setVideoFile(videoFile)
        self.localVideoFile:str|None = None
        self.videoInfo:dict = None
        self.infoFile:str = None
        if infoFile is not None:
            self.setInfoFile(infoFile)
        self.chatFile:str|None = None
        self.parsedChat:ParsedChat|None = None
        if chatFile is not None:
            self.setChatFile(chatFile)

    def __repr__(self):
        return f"SourceFile(streamer=\"{self.streamer}\", videoId=\"{self.videoId}\", videoFile=\"{self.videoFile}\", infoFile=\"{self.infoFile}\", chatFile=\"{self.chatFile}\")"

    def isComplete(self):
        return self.videoFile is not None and self.infoFile is not None

    def setInfoFile(self, infoFile:str):
        if self.infoFile == infoFile:
            return
        assert self.infoFile is None, f"Cannot overwrite existing info file {self.chatFile} with new file {infoFile}"
        assert infoFile.endswith(getConfig('internal.infoExt')) and os.path.isfile(
            infoFile) and os.path.isabs(infoFile)
        self.infoFile = infoFile
        with open(infoFile) as file:
            self.infoJson = trimInfoDict(json.load(file))
        self.duration = self.infoJson['duration']
        self.startTimestamp = self.infoJson['timestamp']
        self.endTimestamp = self.duration + self.startTimestamp

    def setVideoFile(self, videoFile:str):
        if self.videoFile == videoFile:
            return
        assert self.videoFile is None, f"Cannot overwrite existing video file {self.chatFile} with new file {videoFile}"
        assert any((videoFile.endswith(videoExt) for videoExt in getConfig('internal.videoExts'))
                   ) and os.path.isfile(videoFile) and os.path.isabs(videoFile)
        self.videoFile = videoFile
        self.downloadTime = convertToDatetime(os.path.getmtime(videoFile))

    def setChatFile(self, chatFile:str):
        if self.chatFile == chatFile:
            return
        assert self.chatFile is None, f"Cannot overwrite existing chat file {self.chatFile} with new file {chatFile}"
        assert chatFile.endswith(getConfig('internal.chatExt')) and os.path.isfile(
            chatFile) and os.path.isabs(chatFile)
        self.chatFile = chatFile
        
    def tryParsingChatFile(self) -> bool:
        if self.streamer in getConfig('main.streamersParseChatList'):
            if self.chatFile is not None:
                self.parsedChat = ParsedChat(self, self.chatFile)
                return True
        return False

    def getVideoFileInfo(self):
        if self.videoInfo is None:
            self.videoInfo = getVideoInfo(
                self.videoFile if self.localVideoFile is None else self.localVideoFile)
        return self.videoInfo


def scanFiles():
    # newFiles = set()
    # newFilesByStreamer = dict()
    newFilesByVideoId:Dict[str, SourceFile] = dict()
    basepath = getConfig('main.basepath')
    outputDirectory = getConfig('main.outputDirectory')
    videoExts = getConfig('internal.videoExts')
    videoIdRegex = getConfig('internal.videoIdRegex')
    chatExt = getConfig('internal.chatExt')
    infoExt = getConfig('internal.infoExt')
    globalAllStreamers = [name for name in os.listdir(basepath) if
                      (name not in ("NA", outputDirectory) and 
                       os.path.isdir(os.path.join(basepath, name)))]
    for streamer in globalAllStreamers:
        logger.info(f"Scanning streamer {streamer} ")
        newStreamerFiles:List[SourceFile] = []
        streamerBasePath = os.path.join(basepath, streamer, 'S1')
        count = 0
        for filename in (x for x in os.listdir(streamerBasePath) if any((x.endswith(ext) for ext in (videoExts + [infoExt, chatExt])))):
            filepath = os.path.join(streamerBasePath, filename)
            if filepath in scanned.allScannedFiles:
                continue
            filenameSegments = re.split(videoIdRegex, filename)
            # print(filenameSegments)
            if len(filenameSegments) < 3:
                continue
            assert len(filenameSegments) >= 3
            videoId = filenameSegments[-2]
            # print(videoId, filepath, sep=' '*8)
            file = None
            if videoId not in scanned.allFilesByVideoId.keys() and videoId not in newFilesByVideoId.keys():
                if any((filename.endswith(videoExt) for videoExt in videoExts)):
                    file = SourceFile(streamer, videoId, videoFile=filepath)
                    # filesBySourceVideoPath[filepath] = file
                elif filename.endswith(infoExt):
                    try:
                        file = SourceFile(streamer, videoId, infoFile=filepath)
                    except Exception as ex:
                        logger.error(f"Unable to parse info file {filepath}")
                        logger.exception(ex)
                else:
                    assert filename.endswith(chatExt)
                    file = SourceFile(streamer, videoId, chatFile=filepath)
                # scanned.allFilesByVideoId[videoId] = file
                newFilesByVideoId[videoId] = file
                newStreamerFiles.append(file)
            else:
                file = scanned.allFilesByVideoId[videoId] if videoId in scanned.allFilesByVideoId.keys(
                ) else newFilesByVideoId[videoId]
                if any((filename.endswith(videoExt) for videoExt in videoExts)):
                    file.setVideoFile(filepath)
                    # filesBySourceVideoPath[filepath] = file
                elif filename.endswith(infoExt):
                    try:
                        file.setInfoFile(filepath)
                    except Exception as ex:
                        logger.error(f"Unable to parse info file {filepath}")
                        logger.exception(ex)
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
        newCompleteFiles = []
        for i in reversed(range(len(newStreamerFiles))):
            file = newStreamerFiles[i]
            if file.isComplete():
                if file.streamer not in scanned.allStreamersWithVideos:
                    scanned.allFilesByStreamer[file.streamer] = []
                    scanned.allStreamersWithVideos.append(file.streamer)
                scanned.allScannedFiles.add(file.videoFile)
                scanned.allScannedFiles.add(file.infoFile)
                if file.chatFile is not None:
                    scanned.allScannedFiles.add(file.chatFile)
                scanned.filesBySourceVideoPath[file.videoFile] = file
                scanned.allFilesByVideoId[file.videoId] = file
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
            #    del scanned.allFilesByVideoId[file.videoId]
            #    del streamerFiles[i]
        logger.info(f"Scanned streamer {streamer} with {count} files")
        if len(newStreamerFiles) > 0:
            if streamer not in scanned.allFilesByStreamer.keys():
                # scanned.allStreamersWithVideos.append(streamer)
                scanned.allFilesByStreamer[streamer] = newCompleteFiles
            else:  # streamer already had videos scanned in
                scanned.allFilesByStreamer[streamer].extend(newCompleteFiles)
    #Can only parse chat files properly when all streamers have been scanned in
    for file in newFilesByVideoId.values():
        file.tryParsingChatFile()
    
    scanned.allStreamersWithVideos = list(scanned.allFilesByStreamer.keys())
    logger.info(f"Step 0: {scanned.allStreamersWithVideos}")

    # [OLD]       1. Build sorted (by start time) array of sessions by streamer
    # for streamer in scanned.allStreamersWithVideos:
    #    allStreamerSessions[streamer] = []
    #    for file in allFilesByStreamer[streamer]:
    # 1. Add new sessions for each streamer

    for sessionList in scanned.allStreamerSessions.values():
        sessionList.sort(key=lambda x: x.startTimestamp)
    # for streamer in scanned.allStreamersWithVideos:
    #    scanned.allStreamerSessions[streamer].sort(key=lambda x:x.startTimestamp)
    logger.info(f"Step 1: {sum((len(x) for x in scanned.allStreamerSessions.values()))}")

def saveFiledata(filepath: str):
    logger.info("Starting pickle dump")
    with open(filepath, 'wb') as file:
        pickle.dump(scanned.allFilesByVideoId, file)
        logger.info("Pickle dump successful")


def loadFiledata(filepath: str):  # suppresses all errors
    try:
        with open(filepath, 'rb') as file:
            logger.info("Starting pickle load...")
            pickleData = pickle.load(file)
            scanned.allFilesByVideoId = pickleData
            scanned.allFilesByStreamer = {}  # string:[SourceFile]
            scanned.allStreamersWithVideos = []
            scanned.allStreamerSessions = {}
            scanned.allScannedFiles = set()
            scanned.filesBySourceVideoPath = {}
            for file in scanned.allFilesByVideoId.values():
                scanned.filesBySourceVideoPath[file.videoFile] = file
            for file in sorted(scanned.allFilesByVideoId.values(), key=lambda x: x.startTimestamp):
                if file.streamer not in scanned.allStreamersWithVideos:
                    scanned.allFilesByStreamer[file.streamer] = []
                    scanned.allStreamersWithVideos.append(file.streamer)
                scanSessionsFromFile(file)
                scanned.allFilesByStreamer[file.streamer].append(file)
                scanned.allScannedFiles.add(file.videoFile)
                scanned.allScannedFiles.add(file.infoFile)
                if file.chatFile is not None:
                    scanned.allScannedFiles.add(file.chatFile)
            logger.info("Pickle load successful")
    except FileNotFoundError:
        logger.warning("Pickle load failed due to missing file, this is not an issue for the first run or if the file has been deleted")
    except Exception as ex:
        logger.error("Pickle load failed! Exception:")
        logger.error(ex)


def initialize():
    dataFilepath = getConfig('main.dataFilepath')
    if len(scanned.allFilesByVideoId) == 0:
        loadFiledata(dataFilepath)
    oldCount = len(scanned.allFilesByVideoId)
    scanFiles()
    if len(scanned.allFilesByVideoId) != oldCount:
        saveFiledata(dataFilepath)


def reinitialize():
    dataFilepath = getConfig('main.dataFilepath')
    scanned.allFilesByVideoId = {}
    loadFiledata(dataFilepath)
    initialize()


def reloadAndSave():
    dataFilepath = getConfig('main.dataFilepath')
    scanned.allFilesByVideoId = {}
    scanned.allFilesByStreamer = {}  # string:[SourceFile]
    scanned.allStreamersWithVideos = []
    scanned.allStreamerSessions = {}
    scanned.allScannedFiles = set()
    scanned.filesBySourceVideoPath = {}
    scanFiles()
    saveFiledata(dataFilepath)

