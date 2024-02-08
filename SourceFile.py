import os
import subprocess
import json
from .ParsedChat import ParsedChat, convertToDatetime

if __debug__:
    from .config import *

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
    def __init__(self, streamer: str, videoId: str, *, videoFile=None, infoFile=None, chatFile=None):
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
