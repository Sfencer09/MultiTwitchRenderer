from datetime import datetime
import os
import re
import subprocess
import json
from typing import Dict, List, Set

from Session import scanSessionsFromFile
from .ParsedChat import ParsedChat, convertToDatetime

if __debug__:
    from .config import *

if 'allFilesByVideoId' not in globals():
    print('Creating data structures')
    allFilesByVideoId: Dict[str, SourceFile] = {}  # string:SourceFile
    allFilesByStreamer: Dict[str, SourceFile] = {}  # string:[SourceFile]
    allStreamersWithVideos: List[str] = []
    allStreamerSessions: Dict[str, List[Session]] = {}
    allScannedFiles: Set[str] = set()
    filesBySourceVideoPath: Dict[str, SourceFile] = {}

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


def trimInfoDict(infoDict: dict):
    newDict = dict(infoDict)
    del newDict['thumbnails']
    del newDict['formats']
    del newDict['subtitles']
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
        self.parsedChat:str|None = None
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
        assert infoFile.endswith(infoExt) and os.path.isfile(
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
        assert any((videoFile.endswith(videoExt) for videoExt in videoExts)
                   ) and os.path.isfile(videoFile) and os.path.isabs(videoFile)
        self.videoFile = videoFile
        self.downloadTime = convertToDatetime(os.path.getmtime(videoFile))

    def setChatFile(self, chatFile:str):
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
