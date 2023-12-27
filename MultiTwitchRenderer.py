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
import os, subprocess, json, time, math, pickle, re, queue, threading, shutil, random, sys
from functools import reduce
from datetime import datetime, timezone, time, timedelta
from fuzzysearch import find_near_matches
from pprint import pprint
from shlex import quote
import time as ttime

def getVideoInfo(videoFile:str):
    probeResult = subprocess.run(['ffprobe', '-v', 'quiet',
                                  '-print_format', 'json=c=1',
                                  '-show_format', '-show_streams',
                                  videoFile], capture_output=True)
    #print(probeResult)
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
        if chatFile is not None:
            self.setChatFile(chatFile)
        self.parsedChat = None
    def __repr__(self):
        return f"SourceFile(streamer=\"{self.streamer}\", videoId=\"{self.videoId}\", videoFile=\"{self.videoFile}\", infoFile=\"{self.infoFile}\", chatFile=\"{self.chatFile}\")"

    def isComplete(self):
        return self.videoFile is not None and self.infoFile is not None
    def setInfoFile(self, infoFile):
        assert self.infoFile is None
        assert infoFile.endswith(infoExt) and os.path.isfile(infoFile) and os.path.isabs(infoFile)
        self.infoFile = infoFile
        with open(infoFile) as file:
            self.infoJson = trimInfoDict(json.load(file))
        self.duration = self.infoJson['duration']
        self.startTimestamp = self.infoJson['timestamp']
        self.endTimestamp = self.duration + self.startTimestamp
    def setVideoFile(self, videoFile):
        assert self.videoFile is None
        assert videoFile.endswith(videoExt) and os.path.isfile(videoFile) and os.path.isabs(videoFile)
        self.videoFile = videoFile
        self.downloadTime = convertToDatetime(os.path.getmtime(videoFile))
    def setChatFile(self, chatFile):
        assert self.chatFile is None
        assert chatFile.endswith(chatExt) and os.path.isfile(chatFile) and os.path.isabs(chatFile)
        self.chatFile = chatFile
    def getVideoFileInfo(self):
        if self.videoInfo is None:
            self.videoInfo = getVideoInfo(self.videoFile if self.localVideoFile is None else self.localVideoFile)
        return self.videoInfo

class ParsedChat:
    def __init__(self, chatFile:str):
        with open(chatFile) as chatFileContents:
            chatJson = json.load(chatFileContents)
        #print(chatFile)
        nightbotGroupComments = []
        groupEditComments = []
        groups = []
        lastCommandComment = None
        #self.chatJson = chatJson
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
                    #print(fullMessage)
                    #print(group)
                    convertedTime = datetime.fromisoformat(timestamp)
                    #if len(groups) == 0 or set(group) != set(groups[-1].group):
                    groups.append({'group':group, 'time':convertedTime})
                lastCommandComment = None
            else:
                if firstMessageFrag.lower().strip() in ('!who', '!group'):
                    lastCommandComment = comment
                elif (any((badge['setID']=='moderator' for badge in comment['message']['userBadges'])) and 
                    re.sub(r'\s+', ' ', fullMessage.lower()).startswith('!editcom !group')):
                    groupEditComments.append(comment)
                    newCommandText = fullMessage[6+fullMessage.lower().index('!group'):]
                    group = parsePlayersFromGroupMessage(newCommandText)
                    #print(fullMessage)
                    #print(newCommandText)
                    #print(group)
                    convertedTime = datetime.fromisoformat(timestamp)
                    groups.append({'group':group, 'time':convertedTime})
        self.nightbotGroupComments = nightbotGroupComments
        self.groupEditComments = groupEditComments
        self.groups = groups


    def getGroupAtTimestamp(self, timestamp:int|float|str|datetime):
        dt = convertToDatetime(timestamp)
        lastMatch = []
        for group in self.groups:
            if group.time < dt:
                lastMatch = group.group
            else:
                break
        return lastMatch

    def getAllPlayersOverRange(self, startTimestamp:int|float|str|datetime, endTimestamp:int|float|str|datetime):
        start = convertToDatetime(startTimestamp)
        end = convertToDatetime(endTimestamp)
        allPlayers = set()
        lastMatch = []
        for group in self.groups:
            if len(lastMatch)==0 and group['time'] < start:
                lastMatch = group['group'] # get last group before this range, in case no commands are found
            if start < group['time'] < end:
                allPlayers.update(group['group']) # command is within range, 
        return allPlayers if len(allPlayers)>0 else lastMatch

class Session:
    def __init__(self, file:SourceFile, game:str, startTimestamp:int|float, endTimestamp:int|float):
        self.startTimestamp = startTimestamp
        self.endTimestamp = endTimestamp
        self.file = file
        self.game = game
    def hasOverlap(self:SourceFile, cmp:SourceFile, useChat=True):
        if self.startTimestamp > cmp.endTimestamp or self.endTimestamp < cmp.startTimestamp:
            return False
        if useChat:
            if self.file.parsedChat is not None:
                selfPlayers = self.file.parsedChat.getAllPlayersOverRange(self.startTimestamp-15, self.endTimestamp)
                if cmp.file.streamer in selfPlayers:
                    return True
            if cmp.file.parsedChat is not None:
                cmpPlayers = cmp.file.parsedChat.getAllPlayersOverRange(cmp.startTimestamp-15, self.endTimestamp)
                if self.file.streamer in cmpPlayers:
                    return True
        return self.game == cmp.game and (not useChat or (self.file.parsedChat is None and cmp.file.parsedChat is None))
    def __repr__(self):
        return f"Session(game=\"{self.game}\", startTimestamp={self.startTimestamp}, endTimestamp={self.endTimestamp}, file=\"{self.file}\")"

print("Starting")

# %%
basepath = '/mnt/pool2/media/Twitch Downloads/'
localBasepath = '/mnt/scratch1/'
outputDirectory = "Rendered Multiviews"

mainStreamers = ('ChilledChaos',)# 'ZeRoyalViking')
globalAllStreamers = [name for name in os.listdir(basepath) if
                      (name not in ("NA", outputDirectory) and 
                       os.path.isdir(os.path.join(basepath, name)))]
secondaryStreamers = [name for name in globalAllStreamers if name not in mainStreamers]

streamerAliases = {'AphexArcade':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'APlatypus':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'ArtificialActr':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'BonsaiBroz':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm',
                                'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   #'BryceMcQuaid':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'chibidoki':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Courtilly':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'CrashVS':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'DooleyNotedGaming':['Jeremy'], 
                   'ElainaExe':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'emerome':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'FlanelJoe':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'HeckMuffins':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Junkyard129':['Junkyard', 'Junk', 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'KaraCorvus':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Kn0vis':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Kruzadar':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'KYR_SP33DY':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm',
                                 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'LarryFishburger':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'MG4R':['Greg', 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'MicheleBoyd':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'PastaroniRavioli':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'SideArms4Reason':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm', #hacky override for Twitch Rivals 12/7/23
                                      'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'TheRealShab':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'ToastyFPS':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'VikramAFC':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Your__Narrator': ['YourNarrator'],
                  }

nongroupGames = ('Just Chatting', "I'm Only Sleeping")


characterReplacements = {'?':'？', '/':'', '\\':''}

threadCount = 16 #os.cpu_count()

def calcTileWidth(numTiles):
    return int(math.sqrt(numTiles-1.0))+1

def trimInfoDict(infoDict:dict):
    newDict = dict(infoDict)
    del newDict['thumbnails']
    del newDict['formats']
    del newDict['subtitles']
    del newDict['http_headers']
    return newDict

defaultSetPTS = "PTS-STARTPTS"
videoSetPTS = "N/FRAME_RATE/TB"
audioSetPTS = "N/SR/TB"
apts = defaultSetPTS
vpts = defaultSetPTS

videoExt = '.mp4'
infoExt = '.info.json'
chatExt = '.rechat.twitch-gql-20221228.json'
otherExts = ['.description', '.jpg']
videoIdRegex = r"(v[\d]+)"
streamersParseChatList = ('ChilledChaos', 'ZeRoyalViking')

def getHasFfmpegCuda(ffmpegPath=''):
    process = subprocess.run([f"{ffmpegPath}ffmpeg", "-version"], capture_output=True)
    print(process.stdout.decode())
    return '--enable-nvdec' in process.stdout.decode()
HAS_CUDA = getHasFfmpegCuda()
print('NVIDIA hardware video decoding detected' if HAS_CUDA else 'No hardware video decoding detected')

DEFAULT_DATA_FILEPATH = r'./knownFiles.pickle' #r'/home/ubuntu/Documents/MultiTwitchRenderer/allTwitchFiles.pickle'

REDUCED_MEMORY = False

EST_TIMEZONE = timezone(timedelta(hours=-5))
CST_TIMEZONE = timezone(timedelta(hours=-6))
MST_TIMEZONE = timezone(timedelta(hours=-7))
PST_TIMEZONE = timezone(timedelta(hours=-8))
UTC_TIMEZONE = timezone(timedelta(hours=0))
LOCAL_TIMEZONE = CST_TIMEZONE
DAY_START_TIME = time(0, 0, 0, tzinfo=LOCAL_TIMEZONE)

def localDateFromTimestamp(timestamp:int|float):
    dt = datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE)
    startDate = datetime.strftime(startTime, "%Y-%m-%d")

#tileResolutions = [None,"1920:1080", "1920:1080", "1280:720", "960:540", "768:432", "640:360", "640:360"]
#outputResolutions = [None, "1920:1080", "3840:1080", "3840:2160", "3840:2160", "3840:2160", "3840:2160", "4480:2520"]
outputResolutions = [None, (1920,1080), (3840,1080), (3840,2160), (3840,2160), (3840,2160), (3840,2160), (4480,2520)]
outputBitrates = [None,    "6M",        "12M",       "20M",       "25M",       "25M",       "30M",       "40M"]

def parsePlayersFromGroupMessage(message:str):
    players = []
    messageLowercase = message.lower()
    for streamer in globalAllStreamers:
        fuzzymatches = find_near_matches(streamer.lower(), messageLowercase, max_l_dist=1)
        if len(fuzzymatches) > 0:
            players.append(streamer)
        elif streamer in streamerAliases.keys():
            for alias in streamerAliases[streamer]:
                fuzzymatches = find_near_matches(alias.lower(), messageLowercase, max_l_dist=1)
                if len(fuzzymatches) > 0:
                    players.append(streamer)
                    break
    return players

def convertToDatetime(timestamp:int|float|str|datetime):
    if isinstance(timestamp, int) or isinstance(timestamp, float):
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
    elif isinstance(timestamp, str):
        dt = datetime.fromisoformat(timestamp)
    elif isinstance(timestamp, datetime):
        dt = timestamp
    else:
        raise TypeError(f"Invalid type '{type(timestamp)}' for timestamp '{str(timestamp)}'")
    return dt

#print(parsePlayersFromGroupMessage('Chilled is playing with Junkyard129, Kruzadar, KYR_SP33DY, LarryFishburger, and YourNarrator!'))

#0: Build filesets for lookup and looping; pair video files with their info files (and chat files if present)
if 'allFilesByVideoId' not in globals():
    print('Creating data structures')
    allFilesByVideoId = {} #string:SourceFile
    allFilesByStreamer = {} #string:[SourceFile]
    allStreamersWithVideos = []
    allStreamerSessions = {}
    allScannedFiles = set()
    filesBySourceVideoPath = {}

def scanSessionsFromFile(file:SourceFile):
    streamer = file.streamer
    if streamer not in allStreamerSessions.keys():
        allStreamerSessions[streamer] = []
    chapters = file.infoJson['chapters']
    startTime = file.startTimestamp
    #if streamer not in allStreamerSessions.keys():
    #    allStreamerSessions[streamer] = []
    for chapter in chapters:
        game = chapter['title']
        chapterStart = startTime + chapter['start_time']
        chapterEnd = startTime + chapter['end_time']
        session = Session(file, game, chapterStart, chapterEnd)
        allStreamerSessions[streamer].append(session)

def scanFiles():
    newFiles = set()
    for streamer in globalAllStreamers:
        print(f"Scanning streamer {streamer} ", end='')
        streamerFiles = []
        streamerBasePath = os.path.join(basepath, streamer, 'S1')
        count = 0
        for filename in (x for x in os.listdir(streamerBasePath) if any((x.endswith(ext) for ext in (videoExt, infoExt, chatExt)))):
            filepath = os.path.join(streamerBasePath, filename)
            if filepath in allScannedFiles:
                continue
            filenameSegments = re.split(videoIdRegex, filename)
            #print(filenameSegments)
            if len(filenameSegments) < 3:
                continue
            assert len(filenameSegments) >= 3
            videoId = filenameSegments[-2]
            #print(videoId, filepath, sep=' '*8)
            if count % 10 == 0:
                print('.', end='')
            file = None
            if videoId not in allFilesByVideoId.keys():
                if filename.endswith(videoExt):
                    file = SourceFile(streamer, videoId, videoFile=filepath)
                    filesBySourceVideoPath[filepath] = file
                elif filename.endswith(infoExt):
                    file = SourceFile(streamer, videoId, infoFile=filepath)
                else:
                    assert filename.endswith(chatExt)
                    file = SourceFile(streamer, videoId, chatFile=filepath)
                allFilesByVideoId[videoId] = file
                streamerFiles.append(file)
            else:
                file = allFilesByVideoId[videoId]
                if filename.endswith(videoExt):
                    file.setVideoFile(filepath)
                    filesBySourceVideoPath[filepath] = file
                elif filename.endswith(infoExt):
                    file.setInfoFile(filepath)
                else:
                    assert filename.endswith(chatExt)
                    file.setChatFile(filepath)
                    if streamer in streamersParseChatList:
                        file.parsedChat = ParsedChat(filepath)
                if file.isComplete():
                    newFiles.add(file)
            allScannedFiles.add(filepath)
            count += 1
        count = 0
        print('*', end='')
        for i in reversed(range(len(streamerFiles))):
            file = streamerFiles[i]
            if file.isComplete():
                if file.chatFile is not None and streamer in streamersParseChatList:
                    file.parsedChat = ParsedChat(file.chatFile)
                    if count % 10 == 0:
                        print('.', end='')
                    count += 1
                else:
                    file.parsedChat = None
                #filesBySourceVideoPath[file.videoPath] = file
            else:
                #print(f"Deleting incomplete file at index {i}: {streamerFiles[i]}")
                if file.videoFile is not None:
                    del filesBySourceVideoPath[file.videoFile]
                del allFilesByVideoId[file.videoId]
                del streamerFiles[i]
        print(f"\nScanned streamer {streamer} with {len(streamerFiles)} files")
        if len(streamerFiles) > 0:
            if streamer not in allStreamersWithVideos: 
                allStreamersWithVideos.append(streamer)
                allFilesByStreamer[streamer] = streamerFiles
            else: #streamer already had videos scanned in
                allFilesByStreamer[streamer].extend(streamerFiles)
                
    print("Step 0: ", allStreamersWithVideos, end="\n\n\n")

    # [OLD]       1. Build sorted (by start time) array of sessions by streamer
    #for streamer in allStreamersWithVideos:
    #    allStreamerSessions[streamer] = []
    #    for file in allFilesByStreamer[streamer]:
    
    # 1. Add new sessions for each streamer
    for file in newFiles:
        scanSessionsFromFile(file)
        #chapters = file.infoJson['chapters']
        #startTime = file.startTimestamp
        #streamer = file.streamer
        #if streamer not in allStreamerSessions.keys():
        #    allStreamerSessions[streamer] = []
        #for chapter in chapters:
        #    game = chapter['title']
        #    chapterStart = startTime + chapter['start_time']
        #    chapterEnd = startTime + chapter['end_time']
        #    session = Session(file, game, chapterStart, chapterEnd)
        #    allStreamerSessions[streamer].append(session)
    for streamer in allStreamersWithVideos:
        allStreamerSessions[streamer].sort(key=lambda x:x.startTimestamp)
    print("Step 1: ", sum((len(x) for x in allStreamerSessions.values())), end="\n\n\n")

#class SourceFile:
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
#class ParsedChat:
#    self.nightbotGroupComments:
#    self.groupEditComments = groupEditComments
#    self.groups = groups
#    getGroup(self, timestamp:int|float)
#class Session:
#    def __init__(self, file:SourceFile, game:str, startTimestamp:int, endTimestamp:int)
#    file:SourceFile
#    game:str
#    startTimestamp:int
#    endTimestamp:int
#    hasOverlap(self, cmp:Session, useChat:bool=True):bool
#allFilesByVideoId:{str:SourceFile}
#allFilesByStreamer:{str:SourceFile[]}
#allStreamersWithVideos:str[]
#characterReplacements:{str:str}
#def calcTileWidth(numTiles:int):int
#tileResolutions:str[]
#outputResolutions:str[]

def getVideoOutputPath(streamer, date):
    return os.path.join(basepath, outputDirectory, "S1", f"{outputDirectory} - {date} - {streamer}.mkv")

def insertSuffix(outpath, suffix):
    dotIndex = outpath.rindex('.')
    return outpath[:dotIndex]+suffix+outpath[dotIndex:]

def calcResolutions(numTiles, maxNumTiles):
    tileWidth = calcTileWidth(numTiles)
    maxTileWidth = calcTileWidth(maxNumTiles)
    maxOutputResolution = outputResolutions[maxTileWidth]
    scaleFactor = min(maxOutputResolution[0] // (16*tileWidth), maxOutputResolution[1] // (9*tileWidth))
    tileX = scaleFactor * 16
    tileY = scaleFactor * 9
    outputX = tileX * tileWidth
    outputY = tileY * tileWidth
    return (f"{tileX}:{tileY}", f"{outputX}:{outputY}")

def generateLayout(numTiles):
    tileWidth = calcTileWidth(numTiles)
    def generateLE(tileNum): # generateLayoutElement
        x = tileNum % tileWidth
        y = tileNum // tileWidth
        def generateLEC(coord, letter): # generateLayoutElementComponent
            if coord == 0:
                return "0"
            return "+".join([f"{letter}{n}" for n in range(coord)])
        return f"{generateLEC(x,'w')}_{generateLEC(y,'h')}"
    return "|".join([generateLE(n) for n in range(numTiles)])

def pretty_print(clas, indent=0):
    output = ' ' * indent +  type(clas).__name__ +  ':\n'
    indent += 4
    for k,v in clas.__dict__.items():
        if '__dict__' in dir(v):
            output += pretty_print(v,indent)
        else:
            output += ' ' * indent +  k + ': ' + str(v) + '\n'

def toFfmpegTimestamp(ts:int|float):
    return f"{int(ts)//3600:02d}:{(int(ts)//60)%60:02d}:{float(ts%60):02f}"


def generateTilingCommandMultiSegment(mainStreamer, targetDate,
                                      outputFile=None, *,
                                      drawLabels=False,
                                      startTimeMode='mainSessionStart',
                                      endTimeMode='mainSessionEnd',
                                      logLevel=2, #max logLevel = 4
                                      sessionTrimLookback=1,
                                      #sessionTrimLookahead=-1,
                                      outputCodec='libx264',
                                      encodingSpeedPreset='medium',
                                      useHardwareAcceleration=0, #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale, bit 3(4)=(unsupported) encode
                                      maxHwaccelFiles=None,
                                      minimumTimeInVideo=900,
                                      cutMode='chunked',
                                      useChat=True,
                                      ffmpegPath=''):
    assert startTimeMode in ('mainSessionStart', 'allOverlapStart'), f"Unknown startTimeMode value: {str(startTimeMode)}"
    assert endTimeMode in ('mainSessionEnd', 'allOverlapEnd'), f"Unknown endTimeMode value: {str(endTimeMode)}"
    assert outputCodec in ('libx264', 'libx265', 'h264_nvenc'), f"Unknown output codec: {str(outputCodec)}"
    assert encodingSpeedPreset in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'), f"Unknown encoding speed preset: {str(encodingSpeedPreset)}"
    assert useHardwareAcceleration in tuple(range(4)), f"Unknown useHardwareAcceleration value: {str(useHardwareAcceleration)}"
    assert cutMode in ('trim', 'segment', 'chunked'), f"Unknown cutMode value: {str(cutMode)}"
    if outputCodec in ('h264_nvenc', 'hevc_nvenc'):
        assert useHardwareAcceleration&4==4, f"Must enable hardware encoding bit in useHardwareAcceleration if using hardware-accelerated output codec {outputCodec}"
    otherStreamers = [name for name in allStreamersWithVideos if name is not mainStreamer]

    #2. For a given day, target a streamer and find the start and end times of their sessions for the day
    targetDateStartTime = datetime.combine(datetime.fromisoformat(targetDate), DAY_START_TIME)
    targetDateEndTime = targetDateStartTime + timedelta(days=1)
    if outputFile is None:
        outputFile = getVideoOutputPath(mainStreamer, targetDate)
    print(targetDate, targetDateStartTime, targetDateEndTime)
    mainSessionsOnTargetDate = list(filter(lambda x: targetDateStartTime <= datetime.fromtimestamp(x.startTimestamp, tz=UTC_TIMEZONE) <= targetDateEndTime, allStreamerSessions[mainStreamer]))
    if len(mainSessionsOnTargetDate) == 0:
        raise ValueError("Selected streamer does not have any sessions on the target date")
    mainSessionsOnTargetDate.sort(key=lambda x: x.startTimestamp)
    print("\n\n\nStep 2: ", targetDateStartTime, targetDateEndTime)
    pprint(mainSessionsOnTargetDate)
    
    print("\n\nStep 2.1: ")
    groupsFromMainFiles = reduce(list.__add__, (file.parsedChat.groups for file in set((session.file for session in mainSessionsOnTargetDate)) if file.parsedChat is not None), [])
    pprint(groupsFromMainFiles)
    
    #3. For all other streamers, build a sorted array of sessions that have matching games & have time overlap (and/or
        # appear in a !who-type command during that time if rechat is found)
    secondarySessionsArray = []
    secondarySessionsByStreamer = {}
    for streamer in otherStreamers:
        secondarySessionsByStreamer[streamer] = []
        for session in allStreamerSessions[streamer]:
            if any((session.hasOverlap(x, useChat) for x in mainSessionsOnTargetDate)):
                secondarySessionsArray.append(session)
                secondarySessionsByStreamer[streamer].append(session)
        secondarySessionsByStreamer[streamer].sort(key=lambda x: x.startTimestamp)
    print("\n\n\nStep 3: ", secondarySessionsArray)
    if logLevel >= 2:
        pprint(secondarySessionsByStreamer)

    #4. Build a separate array of all sessions from #3, sorted by start time
    secondarySessionsArray.sort(key=lambda x: x.startTimestamp)
    print("\n\n\nStep 4: ")
    if logLevel >= 2:
        pprint(secondarySessionsArray)
    
    #5. Build array of streamers that have sessions in #4, with the target streamer first and the others sorted by
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
    if len(allInputStreamers)==1:
        print("Only one streamer found, nothing to render!")
        return None
        
    #6. For each streamer in #5, build an array of pairs of start & end timestamps for sessions from #3 while
        # combining those that connect
    inputSessionTimestampsByStreamer = {}
    for streamer in allInputStreamers:
        timePairs = []
        inputSessionTimestampsByStreamer[streamer] = timePairs
        for session in secondarySessionsByStreamer[streamer]:
            start, end = session.startTimestamp, session.endTimestamp
            if len(timePairs) == 0:
                timePairs.append([start, end])
            else:
                prevPair = timePairs[-1]
                if start == prevPair[1]:
                    prevPair[1] = end
                else:
                    timePairs.append([start, end])
    print("\n\n\nStep 6: ")
    if logLevel >= 2:
        pprint(inputSessionTimestampsByStreamer)

    #7. Build a sorted array of unique timestamps from #6, truncated to those within the target streamer's first and
        # last sessions (inclusive)
    mainSessionsStartTime = mainSessionsOnTargetDate[0].startTimestamp
    mainSessionsEndTime = mainSessionsOnTargetDate[-1].endTimestamp
    uniqueTimestamps = set((mainSessionsStartTime, mainSessionsEndTime))
    for streamer in allInputStreamers:
        for timePair in inputSessionTimestampsByStreamer[streamer]:
            start, end = timePair
            if start > mainSessionsStartTime or startTimeMode=='allOverlapStart':
                uniqueTimestamps.add(start)
            if end < mainSessionsEndTime or endTimeMode=='allOverlapEnd':
                uniqueTimestamps.add(timePair[1])
    uniqueTimestampsSorted = sorted(uniqueTimestamps)
    allSessionsStartTime = uniqueTimestampsSorted[0]
    allSessionsEndTime = uniqueTimestampsSorted[-1]
    if logLevel >= 1:
        print("\n\n\nStep 7: ", allSessionsStartTime, allSessionsEndTime, 
              mainSessionsStartTime, mainSessionsEndTime, uniqueTimestampsSorted)
        for ts in uniqueTimestampsSorted:
            print(convertToDatetime(ts))
        print(convertToDatetime(uniqueTimestampsSorted[-1])-convertToDatetime(uniqueTimestampsSorted[0]), end='\n\n')

    #8. Build a len(#5) x len(#7)-1 matrix, where each row is the time between the n'th and n+1'th timestamp from #7
        # and the element in each column is either None or the indexed streamer's file(path) for that section of
        # time - should never be more than one
    numSegments = len(uniqueTimestampsSorted)-1
    segmentFileMatrix = [[None for i in range(len(allInputStreamers))] for j in range(numSegments)]
    segmentSessionMatrix = [[None for i in range(len(allInputStreamers))] for j in range(numSegments)]
    for segIndex in range(numSegments):
        #segmentsByStreamerIndex = segmentFileMatrix[segIndex]
        segmentStartTime = uniqueTimestampsSorted[segIndex]
        segmentEndTime = uniqueTimestampsSorted[segIndex+1]# - 1
        def addOverlappingSessions(sessionsList, streamerIndex):
            for session in sessionsList:
                overlapStart = max(segmentStartTime, session.startTimestamp)
                overlapEnd = min(segmentEndTime, session.endTimestamp)
                overlapLength = max(0, overlapEnd - overlapStart)
                if overlapLength > 0:
                    if segmentFileMatrix[segIndex][streamerIndex] is None:
                        segmentFileMatrix[segIndex][streamerIndex] = session.file
                        segmentSessionMatrix[segIndex][streamerIndex] = [session]
                    else:
                        segmentSessionMatrix[segIndex][streamerIndex].append(session)
                        print(segmentSessionMatrix[segIndex][streamerIndex], overlapStart, overlapEnd, segmentStartTime, segmentEndTime)
                        assert segmentFileMatrix[segIndex][streamerIndex] is session.file
        addOverlappingSessions(mainSessionsOnTargetDate, 0)
        for i in range(1, len(allInputStreamers)):
            addOverlappingSessions(secondarySessionsByStreamer[allInputStreamers[i]], i)
    print("\n\n\nStep 8: ")
    if logLevel >= 4:
        pprint(segmentFileMatrix)
    print(allInputStreamers)

    #9. Remove segments of secondary streamers still in games that main streamer has left
    print("\n\nStep 9:")
    for i in range(len(segmentSessionMatrix)):
        print(f"[{' '.join(['x' if item is not None else ' ' for item in segmentSessionMatrix[i]])}]", i,
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[i]),
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[0]))
    for i in range(len(segmentFileMatrix)):
        if segmentSessionMatrix[i][0] is None:
            print([])
            continue
        tempMainGames = set((session.game for session in segmentSessionMatrix[i][0]))
        tempGames = set((session.game for item in segmentSessionMatrix[i][1:] if item is not None for session in item))
        print(tempMainGames, tempGames, str(convertToDatetime(uniqueTimestampsSorted[i]))[:-6],
              str(convertToDatetime(uniqueTimestampsSorted[i+1]))[:-6])

    excludeTrimStreamerIndices = []
    mainStreamerGames = set((session.game for row in segmentSessionMatrix if row[0] is not None for session in row[0] if session.game not in nongroupGames))
    for streamerIndex in range(1, len(allInputStreamers)):
        if not any((session.game in mainStreamerGames for row in segmentSessionMatrix if row[streamerIndex] is not None for session in row[streamerIndex])):
            excludeTrimStreamerIndices.append(streamerIndex)
            #If the trimming process would remove /all/ segments for the given streamer, exclude the streamer from
            # trimming because they probably just have a different game name listed
    print(excludeTrimStreamerIndices)

    if sessionTrimLookback >= 0:
        # Remove trailing footage from secondary sessions, for instance the main streamer changes games while part of the group stays on the previous game
        for i in range(sessionTrimLookback, len(segmentFileMatrix)):
            print(len(segmentSessionMatrix[i-1:]))
            acceptedGames = set((session.game for row in segmentSessionMatrix[i-sessionTrimLookback:] if row[0] is not None for session in row[0] if session.game not in nongroupGames))
            print(acceptedGames, end=' ')
            if len(acceptedGames)==0: #main streamer has no sessions for segment, extend from previous segment with sessions
                for j in range(i-(sessionTrimLookback+1), 0, -1):
                    if segmentSessionMatrix[j][0] is None:
                        continue
                    tempAcceptedGames = set((session.game for session in segmentSessionMatrix[j][0] if session.game not in nongroupGames))
                    if len(tempAcceptedGames) > 0:
                        acceptedGames = tempAcceptedGames
                        break
            print(acceptedGames)
            for streamerIndex in range(1, len(allInputStreamers)):
                if streamerIndex in excludeTrimStreamerIndices:
                    continue
                sessionList = segmentSessionMatrix[i][streamerIndex]
                if sessionList is None:
                    continue
                if not any((session.game in acceptedGames for session in sessionList)):
                    segmentSessionMatrix[i][streamerIndex] = None
                    segmentFileMatrix[i][streamerIndex] = None
    
    # TODO: fill in short gaps (<5 min?) in secondary streamers
    
    for i in range(len(segmentSessionMatrix)):
        print(f"[{' '.join(['x' if item is not None else ' ' for item in segmentSessionMatrix[i]])}]", i,
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[i]),
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[0]))
    
    print("\n\nStep 10:")
    #10. Remove streamers who have less than a minimum amount of time in the video
    print(allInputStreamers, allInputStreamersSortKey)
    for streamerIndex in range(len(allInputStreamers)-1, 0, -1):
        streamer = allInputStreamers[streamerIndex]
        streamerTotalTime = 0
        for i in range(len(segmentSessionMatrix)):
            if segmentSessionMatrix[i][streamerIndex] is not None:
                streamerTotalTime += uniqueTimestampsSorted[i+1]-uniqueTimestampsSorted[i]
        print(streamerIndex, streamer, streamerTotalTime)
        if streamerTotalTime < minimumTimeInVideo:
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
            for session in secondarySessionsByStreamer[streamer]:
                secondarySessionsArray.remove(session)
            del secondarySessionsByStreamer[streamer]
    print(allInputStreamers, allInputStreamersSortKey)
    
    for i in range(len(segmentSessionMatrix)):
        print(f"[{' '.join(['x' if item is not None else ' ' for item in segmentSessionMatrix[i]])}]", i,
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[i]),
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[0]))

    #11. Combine adjacent segments that now have the same set of streamers
    print("\n\nStep 11:")
    for i in range(numSegments-1, 0, -1):
        print(i)
        if all(((segmentFileMatrix[i][stIndex] is None) == (segmentFileMatrix[i-1][stIndex] is None) for stIndex in range(len(allInputStreamers)))):
            del segmentFileMatrix[i]
            del segmentSessionMatrix[i]
            tempTs = uniqueTimestampsSorted[i]
            print(f"Combining segments {str(i)} and {str(i-1)}, dropping timestamp {str(tempTs)}")
            del uniqueTimestampsSorted[i]
            uniqueTimestamps.remove(tempTs)
            numSegments -= 1

    for i in range(len(segmentSessionMatrix)):
        print(f"[{' '.join(['x' if item is not None else ' ' for item in segmentSessionMatrix[i]])}]", i,
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[i]),
              convertToDatetime(uniqueTimestampsSorted[i+1])-convertToDatetime(uniqueTimestampsSorted[0]))
    for i in range(len(segmentSessionMatrix)):
        if segmentSessionMatrix[i][0] is None:
            print([])
            continue
        tempMainGames = set((session.game for session in segmentSessionMatrix[i][0]))
        tempGames = set((session.game for item in segmentSessionMatrix[i][1:] if item is not None for session in item))
        print(tempMainGames, tempGames, str(convertToDatetime(uniqueTimestampsSorted[i]))[:-6],
              str(convertToDatetime(uniqueTimestampsSorted[i+1]))[:-6])

    #12. Build a sorted array of unique filepaths from #8 - these will become the input stream indexes
    inputFilesSorted = sorted(set([item for sublist in segmentFileMatrix for item in sublist if item is not None]),
                              key=lambda x:allInputStreamers.index(x.streamer))
        #12a. Build reverse-lookup dictionary
    inputFileIndexes = {}
    for i in range(len(inputFilesSorted)):
        inputFileIndexes[inputFilesSorted[i]] = i
        #12b. Build input options in order
    inputOptions = []
    inputVideoInfo = []
    for i in range(len(inputFilesSorted)):
        file = inputFilesSorted[i]
        if useHardwareAcceleration&1 == 1:
            if maxHwaccelFiles is None or i < maxHwaccelFiles:
                inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
                #inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
                if useHardwareAcceleration&2 == 2 and cutMode == 'trim':
                    inputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
            else:
                inputOptions.extend(('-threads', str(threadCount//2)))
        inputOptions.append('-i')
        if file.localVideoFile is not None:
            inputOptions.append(file.localVideoFile)
            #inputVideoInfo.append(getVideoInfo(file.localVideoFile))
            inputVideoInfo.append(file.getVideoFileInfo())
            print(file.localVideoFile)
        else:
            inputOptions.append(file.videoFile)
            #inputVideoInfo.append(getVideoInfo(file.videoFile))
            inputVideoInfo.append(file.getVideoFileInfo())
            print(file.videoFile)
    #nullAudioIndex = len(inputFilesSorted)
    if logLevel >= 1:
        print("\n\n\nStep 12: ", inputOptions)
    forceKeyframeTimes = [toFfmpegTimestamp(uniqueTimestampsSorted[i]-allSessionsStartTime) for i in range(1, numSegments)]
    keyframeOptions = ['-force_key_frames', ','.join(forceKeyframeTimes)]
    streamerAudioSampleRates = [None for i in range(len(allInputStreamers))]
    for i in range(len(inputFilesSorted)):
        file = inputFilesSorted[i]
        fileInfo = inputVideoInfo[i]
        streamerIndex = allInputStreamersSortKey[file.streamer]
        audioStreamInfo = [stream for stream in fileInfo['streams'] if stream['codec_type'] == 'audio'][0]
        audioRate = audioStreamInfo['sample_rate']
        streamerAudioSampleRates[streamerIndex] = audioRate
        print(file.streamer, audioRate)
    nullAudioStreamsBySamplerates = {}
    for samplerate in set(streamerAudioSampleRates):
        rateStr = str(samplerate)
        inputIndex = len([x for x in inputOptions if x == '-i'])
        assert inputIndex == len(inputFilesSorted) + len(nullAudioStreamsBySamplerates)
        inputOptions.extend(('-f',  'lavfi', '-i', f'anullsrc=r={rateStr}'))
        nullAudioStreamsBySamplerates[rateStr] = inputIndex
    
    #13. Use #5 and #12 to build output stream mapping orders and build final command along with #12 and #11
    segmentTileCounts = [len(list(filter(lambda x: x is not None, row))) for row in segmentFileMatrix]
    maxSegmentTiles = max(segmentTileCounts)
    maxTileWidth = calcTileWidth(maxSegmentTiles)
    outputResolution = outputResolutions[maxTileWidth]
    outputResolutionStr = f"{str(outputResolution[0])}:{str(outputResolution[1])}"
    outputMapOptions = ['-map', '[vout]']
    outputMetadataOptions = []
    for streamerIndex in range(len(allInputStreamers)):
        outputMapOptions.extend(('-map', f"[aout{streamerIndex}]"))
        streamerName = allInputStreamers[streamerIndex]
        outputMetadataOptions.extend((f"-metadata:s:a:{streamerIndex}", f"title=\"{streamerName}\"",
                                      f"-metadata:s:a:{streamerIndex}", "language=eng"))
    codecOptions = ["-c:a","aac",
         "-c:v", outputCodec,
         "-s", outputResolutionStr]
    if outputCodec in ('libx264', 'h264_nvenc'):
        codecOptions.extend(("-profile:v","high",
         #"-maxrate",outputBitrates[maxTileWidth],
         #"-bufsize","4M",
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
    uploadFilter, downloadFilter = (f"hwupload_cuda", f"hwdownload,format=pix_fmts=yuv420p")
    
    #14. For each row of #8:
    filtergraphStringSegments = []
    filtergraphStringSegmentsV2 = []
    print("\n\n\nStep 13.v2: ", segmentTileCounts, maxSegmentTiles, outputResolution)
    #v2()
    def filtergraphSegmentVersion():
        filtergraphParts = []
        inputSegmentNumbers = [[None for i in range(len(allInputStreamers))] for j in range(numSegments)]
        for fileIndex in range(len(inputFilesSorted)):
            inputFile:SourceFile = inputFilesSorted[fileIndex]
            fileInfo = inputVideoInfo[fileIndex]
            videoStreamInfo = [stream for stream in fileInfo['streams'] if stream['codec_type']=='video'][0]
            fpsRaw = videoStreamInfo['avg_frame_rate'].split('/')
            fpsActual = float(fpsRaw[0]) / float(fpsRaw[1])
            print(inputFile.videoFile, fpsRaw, fpsActual, fpsActual==60)
            fileStartTime = inputFile.startTimestamp
            fileEndTime = inputFile.endTimestamp
            timestamps = []
            segmentIndex = 0
            segmentsPresent = [i for i in range(numSegments) if any((segmentFileMatrix[i][j] is inputFile for j in range(len(allInputStreamers))))]
            print('\n', inputFile.videoFile, segmentsPresent)
            streamerIndex = allInputStreamersSortKey[inputFile.streamer]
            nullVSinkFiltergraphs = [] #for segments that are not wanted, typically leading or trailing ones
            nullASinkFiltergraphs = [] #for segments that are not wanted, typically leading or trailing ones
            for matrixIndex in segmentsPresent:
                segmentStartTime = uniqueTimestampsSorted[matrixIndex]
                segmentEndTime = uniqueTimestampsSorted[matrixIndex+1]# - 1
                startDiff = segmentStartTime - fileStartTime
                if (matrixIndex-1) not in segmentsPresent: #segment is the start of a series of used segments
                    if startDiff > 0: #segment starts partway through the video, need to discard first segment
                        #if matrixIndex == 0:
                        nullVSegName = f"file{fileIndex}V{len(timestamps)}"
                        nullVSinkFiltergraphs.append(f"[{nullVSegName}] nullsink")
                        nullASegName = f"file{fileIndex}A{len(timestamps)}"
                        nullASinkFiltergraphs.append(f"[{nullASegName}] anullsink")
                        timestamps.append(startDiff)
                    inputSegmentNumbers[matrixIndex][allInputStreamersSortKey[inputFile.streamer]] = (len(timestamps), fileIndex)
                else: #segment is not the start of a series of used segments (could be middle or end)
                    assert startDiff > 0 #segment starts partway through the video
                    timestamps.append(startDiff)
                    inputSegmentNumbers[matrixIndex][allInputStreamersSortKey[inputFile.streamer]] = (len(timestamps), fileIndex)
            lastSegment = segmentsPresent[-1]
            lastSegmentEndTime = uniqueTimestampsSorted[lastSegment+1]
            endDiff = fileEndTime - lastSegmentEndTime
            if endDiff > 0:
                print('endDiff', endDiff)
                timestamps.append(lastSegmentEndTime-fileStartTime)
                nullVSegName = f"file{fileIndex}V{len(timestamps)}"
                nullVSinkFiltergraphs.append(f"[{nullVSegName}] nullsink")
                nullASegName = f"file{fileIndex}A{len(timestamps)}"
                nullASinkFiltergraphs.append(f"[{nullASegName}] anullsink")
            segmentFilter = f"segment=timestamps={'|'.join((str(ts) for ts in timestamps))}"
            print(segmentFilter)
            fpsFilter = f"fps=fps=60:round=near, " if fpsActual != 60 else ''
            inputVideoFiltergraph = f"[{fileIndex}:v] {fpsFilter}{segmentFilter} [{']['.join((f'file{fileIndex}V{i}' for i in range(len(timestamps)+1)))}]"
            inputAudioFiltergraph = f"[{fileIndex}:a] a{segmentFilter} [{']['.join((f'file{fileIndex}A{i}' for i in range(len(timestamps)+1)))}]"
            filtergraphParts.extend((inputVideoFiltergraph, inputAudioFiltergraph))
            filtergraphParts.extend(nullVSinkFiltergraphs)
            filtergraphParts.extend(nullASinkFiltergraphs)
        assert all((all(((inputSegmentNumbers[i][j] is None) == (segmentFileMatrix[i][j] is None) for j in range(len(allInputStreamers)))) for i in range(numSegments)))
        for segIndex in range(numSegments):
            segmentStartTime = uniqueTimestampsSorted[segIndex]
            segmentEndTime = uniqueTimestampsSorted[segIndex+1]
            segmentDuration = segmentEndTime - segmentStartTime
            rowSegmentNumbers = []
            numTiles = segmentTileCounts[segIndex]
            tileResolution, segmentResolution = calcResolutions(numTiles, maxSegmentTiles)
            if logLevel >= 2:
                print("\n\nStep 13a.v2: ", segIndex, numTiles, tileResolution, segmentResolution, inputSegmentNumbers[segIndex])
            rowVideoSegmentNames = []
            for streamerIndex in range(len(allInputStreamers)):
                temp = inputSegmentNumbers[segIndex][streamerIndex]
                print(temp)
                if temp is not None:
                    fileSegNum, fileIndex = temp
                    fileInfo = inputVideoInfo[fileIndex]
                    videoStreamInfo = [stream for stream in fileInfo['streams'] if stream['codec_type']=='video'][0]
                    height = videoStreamInfo['height']
                    width = videoStreamInfo['width']
                    isSixteenByNine = (height / 9.0) == (width / 16.0)
                    originalResolution = f"{width}:{height}"
                    needToScale = originalResolution != tileResolution
                    print(inputFilesSorted[fileIndex].videoFile, fileIndex, originalResolution, originalResolution == tileResolution)
                    inputVSegName = f"file{fileIndex}V{fileSegNum}"
                    outputVSegName = f"seg{segIndex}V{streamerIndex}"
                    labelFilter = f", drawtext=text='{str(streamerIndex+1)} {allInputStreamers[streamerIndex]}':fontsize=40:fontcolor=white:x=100:y=10:shadowx=4:shadowy=4" if drawLabels else ''
                    useHwFilterAccel = useHardwareAcceleration & 2 == 2 and (maxHwaccelFiles is None or fileIndex < maxHwaccelFiles)
                    uploadFilter, downloadFilter = (f", hwupload_cuda", f", hwdownload,format=pix_fmts=yuv420p") if useHwFilterAccel and (needToScale or not isSixteenByNine) else ('', '')
                    scaleFilter = f", scale{'_npp' if useHwFilterAccel else ''}={tileResolution}:force_original_aspect_ratio=decrease:{'format=yuv420p:' if useHwFilterAccel else ''}eval=frame" if needToScale else ''
                    padFilter = f", pad{'_opencl' if useHwFilterAccel else ''}={tileResolution}:-1:-1:color=black" if not isSixteenByNine else ''
                    videoFiltergraph = f"[{inputVSegName}] setpts={vpts}{uploadFilter}{scaleFilter}{padFilter}{downloadFilter}{labelFilter} [{outputVSegName}]"
                        #if :
                        #    videoFiltergraph = f"[{inputVSegName}] setpts={vpts}, hwupload_cuda, scale_npp={tileResolution}:force_original_aspect_ratio=decrease:format=yuv420p:eval=frame, pad_opencl={tileResolution}:-1:-1:color=black, hwdownload, format=pix_fmts=yuv420p{labelFilter}, [{outputVSegName}]"
                        #else:
                        #    videoFiltergraph = f"[{inputVSegName}] setpts={vpts}, scale={tileResolution}:force_original_aspect_ratio=decrease:eval=frame, pad={tileResolution}:-1:-1:color=black{labelFilter} [{outputVSegName}]"
                    filtergraphParts.append(videoFiltergraph)
                    rowVideoSegmentNames.append(outputVSegName)
                else:
                    audioRate = streamerAudioSampleRates[streamerIndex]
                    nullAudioIndex = nullAudioStreamsBySamplerates[str(audioRate)]
                    emptyAudioFiltergraph = f"[{nullAudioIndex}] atrim=duration={segmentDuration} [seg{segIndex}A{streamerIndex}]"
                    filtergraphParts.append(emptyAudioFiltergraph)
                    if logLevel >= 4:
                        print("\n\nStep 13b.v2: ", segIndex, streamerIndex)
            #13c. Build xstack intermediate video segments
            numRowSegments = len(rowVideoSegmentNames)
            assert numRowSegments > 0 #should have at least one source file for each segment, otherwise we have a gap we need to account for
            if numRowSegments > 1:
                rowTileWidth = calcTileWidth(numRowSegments)
                print(segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(rowTileWidth-1), rowTileWidth)
                print(segmentResolution != outputResolutionStr, numRowSegments <= rowTileWidth*(rowTileWidth-1))
                scaleToFitFilter = f", scale={outputResolutionStr}:force_original_aspect_ratio=decrease:eval=frame" if segmentResolution != outputResolutionStr else ''
                padFilter = f", pad={outputResolutionStr}:-1:-1:color=black" if numRowSegments <= rowTileWidth*(rowTileWidth-1) else ''
                xstackString = f"[{']['.join(rowVideoSegmentNames)}]xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}{scaleToFitFilter}{padFilter} [vseg{segIndex}]"
                filtergraphParts.append(xstackString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", xstackString, segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(rowTileWidth-1), (segmentResolution != outputResolutionStr), (numRowSegments <= rowTileWidth*(rowTileWidth-1)))
            else:
                filtergraphString = f"[{rowVideoSegmentNames[0]}] copy [vseg{segIndex}]"
                filtergraphParts.append(filtergraphString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", filtergraphString, segmentResolution, outputResolutionStr, numRowSegments)

        #15. Build concat statement of intermediate video and audio segments
        videoConcatFiltergraph = f"[{']['.join(('vseg'+str(n) for n in range(numSegments)))}] concat=n={numSegments}:v=1:a=0 [vout]"
        filtergraphParts.append(videoConcatFiltergraph)
        if logLevel >= 3:
            print("\n\n\nStep 14: ", videoConcatFiltergraph)

        #16. Use #5, #7 and #12a to build individual audio output segments
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
        pprint(inputSegmentNumbers)
        pprint(filtergraphParts)
        #print(nullVSinkFiltergraphs, nullASinkFiltergraphs, segmentFiltergraphs)
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

    print("\n\n\nStep 13.v1: ", segmentTileCounts, maxSegmentTiles, outputResolution)

    # v1
    def filtergraphTrimVersion():
        filtergraphParts = []
        for segIndex in range(numSegments):
            segmentStartTime = uniqueTimestampsSorted[segIndex]
            segmentEndTime = uniqueTimestampsSorted[segIndex+1]
            segmentDuration = segmentEndTime - segmentStartTime
            numTiles = segmentTileCounts[segIndex]
            tileResolution, segmentResolution = calcResolutions(numTiles, maxSegmentTiles)
            #rowFiltergraphSegments = []
            #13a. Build array of filepaths-streamer index pairs using #5 that appear in the row, without Nones
            #13b. Use original start timestamp of each file and #7 to determine starting time within file and add to
                # info array elements
            if logLevel >= 2:
                print("\n\nStep 13a: ", segIndex, segmentStartTime, segmentEndTime, numTiles, tileResolution, segmentResolution)
            rowVideoSegmentNames = []
            for streamerIndex in range(len(allInputStreamers)):
                file = segmentFileMatrix[segIndex][streamerIndex]
                #13b. Use #10a&b and #9a to build intermediate segments
                if file is not None:
                    startOffset = segmentStartTime - file.startTimestamp
                    endOffset = segmentEndTime - file.startTimestamp
                    inputIndex = inputFileIndexes[file]
                    videoSegmentName = f"seg{segIndex}V{streamerIndex}"
                    audioSegmentName = f"seg{segIndex}A{streamerIndex}"
                    audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts={apts} [{audioSegmentName}]"
                    fileInfo = inputVideoInfo[inputIndex]
                    videoStreamInfo = [stream for stream in fileInfo['streams'] if stream['codec_type']=='video'][0]
                    height = videoStreamInfo['height']
                    width = videoStreamInfo['width']
                    isSixteenByNine = (height / 9.0) == (width / 16.0)
                    originalResolution = f"{width}:{height}"
                    needToScale = originalResolution != tileResolution
                    #print(inputFilesSorted[fileIndex].videoFile, fileIndex, originalResolution, originalResolution == tileResolution)
                    fpsRaw = videoStreamInfo['avg_frame_rate'].split('/')
                    fpsActual = float(fpsRaw[0]) / float(fpsRaw[1])
                    #print(inputFile.videoFile, fpsRaw, fpsActual, fpsActual==60)
                    useHwFilterAccel = useHardwareAcceleration & 2 == 2 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles)
                    if not useHwFilterAccel:
                        if outputResolution[0] > width: #upscaling
                            scaleAlgo = ':sws_flags=lanczos'
                        elif outputResolution[0] < width:
                            scaleAlgo = '' #':sws_flags=area'
                        else:
                            scaleAlgo = ''
                    else:
                        scaleAlgo = '' #don't specify for HW-accelerated scaling
                    scaleFilter = f"scale{'_npp' if useHwFilterAccel else ''}={tileResolution}:force_original_aspect_ratio=decrease:{'format=yuv420p:' if useHwFilterAccel else ''}eval=frame{scaleAlgo}" if needToScale else ''
                    padFilter = f"pad{'_opencl' if useHwFilterAccel else ''}={tileResolution}:-1:-1:color=black" if not isSixteenByNine else ''
                    fpsFilter = f"fps=fps=60:round=near" if fpsActual != 60 else ''
                    labelFilter = f"drawtext=text='{str(streamerIndex+1)} {file.streamer}':fontsize=40:fontcolor=white:x=100:y=10:shadowx=4:shadowy=4" if drawLabels else ''
                    trimFilter = f"trim={startOffset}:{endOffset}"
                    timeFilter = f"setpts={vpts}"
                    filtergraphBody = None
                    if needToScale or not isSixteenByNine:
                        if useHardwareAcceleration == 3 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [scaleFilter, padFilter, downloadFilter, fpsFilter, trimFilter, timeFilter, labelFilter]
                        elif useHardwareAcceleration == 2 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [fpsFilter, trimFilter, timeFilter, uploadFilter, scaleFilter, padFilter, downloadFilter, labelFilter]
                        elif useHardwareAcceleration == 1 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [fpsFilter, trimFilter, timeFilter, scaleFilter, padFilter, labelFilter]
                        elif useHardwareAcceleration >= 4:
                            raise Exception("Not implemented yet")
                    if filtergraphBody is None:
                        filtergraphBody = [trimFilter, timeFilter, fpsFilter, scaleFilter, padFilter, labelFilter]
                    videoFiltergraph = f"[{inputIndex}:v] {', '.join([segment for segment in filtergraphBody if segment != ''])} [{videoSegmentName}]"

                    filtergraphParts.append(videoFiltergraph)
                    filtergraphParts.append(audioFiltergraph)
                    rowVideoSegmentNames.append(videoSegmentName)
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex, file, startOffset, endOffset, inputIndex, streamerIndex, videoSegmentName, audioSegmentName)
                else:
                    audioRate = streamerAudioSampleRates[streamerIndex]
                    nullAudioIndex = nullAudioStreamsBySamplerates[str(audioRate)]
                    emptyAudioFiltergraph = f"[{nullAudioIndex}] atrim=duration={segmentDuration} [seg{segIndex}A{streamerIndex}]"
                    filtergraphParts.append(emptyAudioFiltergraph)
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex)
            #13c. Build xstack intermediate video segments
            numRowSegments = len(rowVideoSegmentNames)
            assert numRowSegments > 0 #should have at least one source file for each segment, otherwise we have a gap we need to account for
            if numRowSegments > 1:
                rowTileWidth = calcTileWidth(numRowSegments)
                segmentRes = [int(x) for x in segmentResolution.split(':')]
                scaleToFitFilter = f", scale={outputResolutionStr}:force_original_aspect_ratio=decrease:eval=frame" if segmentResolution != outputResolutionStr else ''
                padFilter = f", pad={outputResolutionStr}:-1:-1:color=black" if numRowSegments <= rowTileWidth*(rowTileWidth-1) else ''
                xstackString = f"[{']['.join(rowVideoSegmentNames)}] xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}{scaleToFitFilter}{padFilter} [vseg{segIndex}]"
                filtergraphParts.append(xstackString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", xstackString, segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(rowTileWidth-1), (segmentResolution != outputResolutionStr), (numRowSegments <= rowTileWidth*(rowTileWidth-1)))
            else:
                filtergraphString = f"[{rowVideoSegmentNames[0]}] copy [vseg{segIndex}]"
                filtergraphParts.append(filtergraphString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", filtergraphString, segmentResolution, outputResolutionStr, numRowSegments)

        #15. Build concat statement of intermediate video and audio segments
        videoConcatFiltergraph = f"[{']['.join(('vseg'+str(n) for n in range(numSegments)))}] concat=n={numSegments}:v=1:a=0 [vout]"
        filtergraphParts.append(videoConcatFiltergraph)
        if logLevel >= 3:
            print("\n\n\nStep 14: ", videoConcatFiltergraph)

        #16. Use #5, #7 and #12a to build individual audio output segments
        for streamerIndex in range(len(allInputStreamers)):
            audioConcatFiltergraph = f"[{']['.join((''.join(('seg',str(n),'A',str(streamerIndex))) for n in range(numSegments)))}] concat=n={numSegments}:v=0:a=1 [aout{streamerIndex}]"
            filtergraphParts.append(audioConcatFiltergraph)
            if logLevel >= 3:
                print("\n\n\nStep 15: ", streamerIndex, audioConcatFiltergraph)
        if logLevel >= 3:
            for fss in filtergraphStringSegments:
                print(fss)
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
    def filtergraphChunkedVersion(): #break it into multiple commands in an effort to limit memory usage
        print("CHUNKED", numSegments)
        commandList = []
        intermediateFilepaths = [os.path.join(localBasepath, 'temp', f"{mainStreamer} - {str(targetDate)} - part {i}.mkv") for i in range(numSegments)]
        audioFiltergraphParts = []
        for segIndex in range(numSegments):
            filtergraphParts = []
            segmentStartTime = uniqueTimestampsSorted[segIndex]
            segmentEndTime = uniqueTimestampsSorted[segIndex+1]
            segmentDuration = segmentEndTime - segmentStartTime
            numTiles = segmentTileCounts[segIndex]
            tileResolution, segmentResolution = calcResolutions(numTiles, maxSegmentTiles)
            #rowFiltergraphSegments = []
            #13a. Build array of filepaths-streamer index pairs using #5 that appear in the row, without Nones
            #13b. Use original start timestamp of each file and #7 to determine starting time within file and add to
                # info array elements
            if logLevel >= 2:
                print("\n\nStep 13a: ", segIndex, segmentStartTime, segmentEndTime, numTiles, tileResolution, segmentResolution)
            rowVideoSegmentNames = []
            rowInputFileCount = 0
            rowFiles = [file for file in segmentFileMatrix[segIndex] if file is not None]
            neededNullSampleRates = set()
            numFilesInRow = len(rowFiles)
            for streamerIndex in range(len(allInputStreamers)):
                if segmentFileMatrix[segIndex][streamerIndex] is None:
                    neededNullSampleRates.add(streamerAudioSampleRates[streamerIndex])
            rowNullAudioStreamsBySamplerates = {}
            nullAudioInputOptions = []
            for samplerate in neededNullSampleRates:
                rateStr = str(samplerate)
                audioInputIndex = numFilesInRow + len(rowNullAudioStreamsBySamplerates)
                nullAudioInputOptions.extend(('-f',  'lavfi', '-i', f'anullsrc=r={rateStr}'))
                rowNullAudioStreamsBySamplerates[rateStr] = audioInputIndex
            
            rowInputOptions = []
            for streamerIndex in range(len(allInputStreamers)):
                file = segmentFileMatrix[segIndex][streamerIndex]
                videoSegmentName = f"seg{segIndex}V{streamerIndex}"
                audioSegmentName = f"seg{segIndex}A{streamerIndex}"
                #13b. Use #10a&b and #9a to build intermediate segments
                if file is not None:
                    startOffset = segmentStartTime - file.startTimestamp
                    endOffset = segmentEndTime - file.startTimestamp
                    inputIndex = rowInputFileCount 
                    fileIndex = inputFileIndexes[file]
                    #audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts={apts} [{audioSegmentName}]"
                    fileInfo = inputVideoInfo[fileIndex]
                    videoStreamInfo = [stream for stream in fileInfo['streams'] if stream['codec_type']=='video'][0]
                    height = videoStreamInfo['height']
                    width = videoStreamInfo['width']
                    isSixteenByNine = (height / 9.0) == (width / 16.0)
                    originalResolution = f"{width}:{height}"
                    needToScale = originalResolution != tileResolution
                    print(inputFilesSorted[fileIndex].videoFile, inputIndex, originalResolution, tileResolution, originalResolution == tileResolution)
                    fpsRaw = videoStreamInfo['avg_frame_rate'].split('/')
                    fpsActual = float(fpsRaw[0]) / float(fpsRaw[1])
                    if useHardwareAcceleration&1 == 1:
                        if maxHwaccelFiles is None or inputIndex < maxHwaccelFiles:
                            rowInputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
                            #rowInputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
                            if useHardwareAcceleration&2 == 2 and cutMode == 'trim':
                                rowInputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
                        else:
                            rowInputOptions.extend(('-threads', str(threadCount//2)))
                    if startOffset != 0:
                        rowInputOptions.extend(('-ss', str(startOffset)))
                    rowInputOptions.append('-i')
                    if file.localVideoFile is not None:
                        rowInputOptions.append(file.localVideoFile)
                    else:
                        rowInputOptions.append(file.videoFile)
                    useHwFilterAccel = useHardwareAcceleration & 2 == 2 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles)
                    #print(file.videoFile, fpsRaw, fpsActual, fpsActual==60)
                    if not useHwFilterAccel:
                        tileHeight = int(tileResolution.split(':')[1])
                        print(f"tileHeight={tileHeight}, video height={height}")
                        if tileHeight > height: #upscaling
                            scaleAlgo = ':flags=lanczos'
                        elif tileHeight < height:
                            scaleAlgo = '' #':flags=area'
                        else:
                            scaleAlgo = ''
                    else:
                        scaleAlgo = '' #don't specify for HW-accelerated scaling
                    scaleFilter = f"scale{'_npp' if useHwFilterAccel else ''}={tileResolution}:force_original_aspect_ratio=decrease:{'format=yuv420p:' if useHwFilterAccel else ''}eval=frame{scaleAlgo}" if needToScale else ''
                    padFilter = f"pad{'_opencl' if useHwFilterAccel else ''}={tileResolution}:-1:-1:color=black" if not isSixteenByNine else ''
                    fpsFilter = f"fps=fps=60:round=near" if fpsActual != 60 else ''
                    labelFilter = f"drawtext=text='{str(streamerIndex+1)} {file.streamer}':fontsize=40:fontcolor=white:x=100:y=10:shadowx=4:shadowy=4" if drawLabels else ''
                    #trimFilter = f"trim={startOffset}:{endOffset}"
                    trimFilter = f"trim=duration={str(segmentDuration)}"
                    timeFilter = f"setpts={vpts}"
                    filtergraphBody = None
                    if needToScale or not isSixteenByNine:
                        if useHardwareAcceleration == 3 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [scaleFilter,padFilter,downloadFilter,fpsFilter,trimFilter,timeFilter,labelFilter]
                        elif useHardwareAcceleration == 2 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [fpsFilter,trimFilter,timeFilter,uploadFilter,scaleFilter,padFilter,downloadFilter,labelFilter]
                        elif useHardwareAcceleration == 1 and (maxHwaccelFiles is None or inputIndex < maxHwaccelFiles):
                            filtergraphBody = [fpsFilter,trimFilter,timeFilter,scaleFilter,padFilter,labelFilter]
                        elif useHardwareAcceleration >= 4:
                            raise Exception("Not implemented yet")
                    if filtergraphBody is None:
                        filtergraphBody = [trimFilter,timeFilter,fpsFilter,scaleFilter,padFilter,labelFilter]
                    videoFiltergraph = f"[{inputIndex}:v] {', '.join([segment for segment in filtergraphBody if segment != ''])} [{videoSegmentName}]"
                    #audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts={apts} [{audioSegmentName}]"
                    audioFiltergraph = f"[{inputIndex}:a] a{trimFilter}, a{timeFilter} [{audioSegmentName}]"
                    
                    filtergraphParts.append(videoFiltergraph)
                    filtergraphParts.append(audioFiltergraph)
                    rowVideoSegmentNames.append(videoSegmentName)
                    rowInputFileCount += 1
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex, file, startOffset, endOffset, inputIndex, streamerIndex, videoSegmentName, audioSegmentName)
                else:
                    audioRate = streamerAudioSampleRates[streamerIndex]
                    nullAudioIndex = rowNullAudioStreamsBySamplerates[str(audioRate)]
                    emptyAudioFiltergraph = f"[{nullAudioIndex}] atrim=duration={segmentDuration} [{audioSegmentName}]"
                    filtergraphParts.append(emptyAudioFiltergraph)
                    #audioFiltergraphParts.append(emptyAudioFiltergraph)
                    if logLevel >= 4:
                        print("\n\nStep 13b: ", segIndex, streamerIndex)
            #13c. Build xstack intermediate video segments
            numRowSegments = len(rowVideoSegmentNames)
            assert numFilesInRow == numRowSegments
            assert numRowSegments > 0 #should have at least one source file for each segment, otherwise we have a gap we need to account for
            rowInputOptions.extend(nullAudioInputOptions)
            if numRowSegments > 1:
                rowTileWidth = calcTileWidth(numRowSegments)
                segmentRes = [int(x) for x in segmentResolution.split(':')]
                scaleToFitFilter = f", scale={outputResolutionStr}:force_original_aspect_ratio=decrease:eval=frame" if segmentResolution != outputResolutionStr else ''
                padFilter = f", pad={outputResolutionStr}:-1:-1:color=black" if numRowSegments <= rowTileWidth*(rowTileWidth-1) else ''
                xstackString = f"[{']['.join(rowVideoSegmentNames)}] xstack=inputs={numRowSegments}:{generateLayout(numRowSegments)}{':fill=black' if rowTileWidth**2!=numRowSegments else ''}{scaleToFitFilter}{padFilter} [vseg{segIndex}]"
                filtergraphParts.append(xstackString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", xstackString, segmentResolution, outputResolutionStr, numRowSegments, rowTileWidth*(rowTileWidth-1), (segmentResolution != outputResolutionStr), (numRowSegments <= rowTileWidth*(rowTileWidth-1)))
            else:
                filtergraphString = f"[{rowVideoSegmentNames[0]}] copy [vseg{segIndex}]"
                filtergraphParts.append(filtergraphString)
                if logLevel >= 3:
                    print("\n\n\nStep 13c: ", filtergraphString, segmentResolution, outputResolutionStr, numRowSegments)
            #print(filtergraphParts)
            commandList.append(reduce(list.__add__, [[f"{ffmpegPath}ffmpeg"],
                rowInputOptions,
                threadOptions,
                ['-filter_complex', ' ; '.join(filtergraphParts)],
                ['-map', f"[vseg{segIndex}]"],
                reduce(list.__add__, [
                    ['-map', f'[seg{str(segIndex)}A{str(streamerIndex)}]'] for streamerIndex in range(len(allInputStreamers))
                ]),
                #outputMetadataOptions,
                codecOptions,
                ["-movflags", "faststart", intermediateFilepaths[segIndex]]]))
        #15. Build concat statement of intermediate video and audio segments
        class LazyConcatFile:
            def __init__(self, contents):
                self.contents = contents
                self.filepath = None
            def __repr__(self):
                if self.filepath is None:
                    while self.filepath is None or os.path.isfile(self.filepath):
                        self.filepath = f"./ffmpegConcatList{random.randrange(0,100000)}.txt"
                    with open(self.filepath, 'w') as lazyfile:
                        lazyfile.write(self.contents)
                else:
                    assert os.path.isfile(self.filepath)
                return self.filepath
            def __del__(self):
                if self.filepath is not None:
                    os.remove(self.filepath)
        commandList.append(reduce(list.__add__, [[f"{ffmpegPath}ffmpeg"],
                ['-f', 'concat',
                 '-safe', '0',
                 '-i', LazyConcatFile("file '" + "'\nfile '".join(intermediateFilepaths)+"'"),
                 '-c', 'copy',
                 '-map', '0'],
                outputMetadataOptions,
                ["-movflags", "faststart", outputFile]]))
        for command in commandList:
            print(command, end='\n')
        return commandList

    if cutMode == 'segment':
        return filtergraphSegmentVersion()
    elif cutMode == 'trim':
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

def saveFiledata(filepath:str):
    with open(filepath, 'wb') as file:
        pickle.dump(allFilesByVideoId, file)
        print("Pickle dump successful")

def loadFiledata(filepath:str): #suppresses all errors
    try:
        with open(filepath, 'rb') as file:
            print("Starting pickle load...")
            pickleData = pickle.load(file)
            global allFilesByVideoId; #allFilesByVideoId = pickle.load(file)
            allFilesByVideoId = pickleData
            #allFilesByVideoId = {} #string:SourceFile
            global allFilesByStreamer; allFilesByStreamer = {} #string:[SourceFile]
            global allStreamersWithVideos; allStreamersWithVideos = []
            global allStreamerSessions; allStreamerSessions = {}
            global allScannedFiles; allScannedFiles = set()
            global filesBySourceVideoPath; fileBySourceVideoPath = {}
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


# %%
def initialize():
    if len(allFilesByVideoId) == 0:
        loadFiledata(DEFAULT_DATA_FILEPATH)
    oldCount = len(allFilesByVideoId)
    scanFiles()
    if len(allFilesByVideoId) != oldCount:
        saveFiledata(DEFAULT_DATA_FILEPATH)

def reinitialize():
    allFilesByVideoId={}
    loadFiledata(DEFAULT_DATA_FILEPATH)
    initialize()


def reloadAndSave():
    global allFilesByVideoId; allFilesByVideoId = {} #string:SourceFile
    global allFilesByStreamer; allFilesByStreamer = {} #string:[SourceFile]
    global allStreamersWithVideos; allStreamersWithVideos = []
    global allStreamerSessions; allStreamerSessions = {}
    global allScannedFiles; allScannedFiles = set()
    global filesBySourceVideoPath; fileBySourceVideoPath = {}
    scanFiles()
    saveFiledata(DEFAULT_DATA_FILEPATH)

#reloadAndSave()
initialize()
print("Initialization complete!")

#testCommand = generateTilingCommandMultiSegment('ChilledChaos', "2023-11-30", f"/mnt/pool2/media/Twitch Downloads/{outputDirectory}/S1/{outputDirectory} - 2023-11-30 - ChilledChaos.mkv")
#testCommands = generateTilingCommandMultiSegment('ZeRoyalViking', "2023-06-28", 
testCommands = generateTilingCommandMultiSegment('ChilledChaos', "2023-12-22", 
                                                 #endTimeMode='allOverlapEnd',
                                                 logLevel=0,
                                                 useHardwareAcceleration=1,#|2,
                                                 sessionTrimLookback=3,
                                                 maxHwaccelFiles=20,
                                                 #useChat=False,
                                                 drawLabels=True,
                                                 ffmpegPath='/home/ubuntu/ffmpeg-cuda/ffmpeg/')


print([extractInputFiles(testCommand) for testCommand in testCommands])
print("\n\n")
for testCommand in testCommands:
    testCommand.insert(-1, '-y')
    testCommand.insert(-1, '-stats_period')
    testCommand.insert(-1, '30')
    #testCommand.insert(-1, )
#print(testCommands)
#testCommandString = formatCommand(testCommand)
testCommandStrings = [formatCommand(testCommand) for testCommand in testCommands]
print(testCommandStrings)
def writeCommandStrings(commandList, testNum=None):
    if testNum is None:
        for i in range(2,1000):
            path = f"/mnt/pool2/media/ffmpeg test{str(i)}.txt"
            if not os.path.isfile(path):
                testNum = i
    path = f"/mnt/pool2/media/ffmpeg test{str(testNum)}.txt"
    print(path)
    with open(path, 'w') as file:
        file.write('\n'.join(testCommandStrings))
        file.write('\necho "Render complete!!"')
def writeCommandScript(commandList, testNum=None):
    if testNum is None:
        for i in range(2,1000):
            path = f"/mnt/pool2/media/ffmpeg test{str(i)}.txt"
            if not os.path.isfile(path):
                testNum = i
    path = f"/mnt/pool2/media/ffmpeg test{str(testNum)}.sh"
    print(path)
    with open(path, 'w') as file:
        file.write(' && \\\n'.join(testCommandStrings))
        file.write(' && \\\necho "Render complete!!"')

#writeCommandStrings(testCommandStrings, 10)
writeCommandScript(testCommandStrings, 11)

# %%

# %%
# Threading time!
#import types
import atexit

errorFilePath = r'./erroredCommands.log'
statusFilePath = r'./renderStatuses.pickle'
logFolder = r'./logs/'
if not os.path.exists(logFolder):
    os.makedirs(logFolder)
COPY_FILES = False
DEFAULT_MAX_LOOKBACK=timedelta(days=30)
if COPY_FILES:
    assert localBasepath.strip(' /\\') != basepath.strip(' /\\')

class QueueItem:
    def __init__(self, commandArray, mainStreamer, fileDate):
        self.fileDate = fileDate
        self.mainStreamer = mainStreamer
        self.commandArray = commandArray
        self.outputPath = commandArray[-1][-1]
        allInputFiles = [filepath for command in commandArray for filepath in extractInputFiles(command) if type(filepath)==str and 'anullsrc' not in filepath]
        print(commandArray)
        allOutputFiles = set([command[-1] for command in commandArray])
        self.sourceFiles = [filesBySourceVideoPath[filepath] for filepath in allInputFiles if filepath not in allOutputFiles]
        self.intermediateFiles = set([command[-1] for command in commandArray[:-1]])
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
        return f"QueueItem(mainStreamer={self.mainStreamer}, fileDate={self.fileDate})"


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
renderStatuses = {}
renderStatusLock = threading.Lock()
renderQueue = queue.PriorityQueue()
if COPY_FILES:
    copyQueue = queue.PriorityQueue()
localFileReferenceCounts = {}
localFileRefCountLock = threading.Lock()

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
    assert status in ("RENDERING","RENDER_QUEUE","COPY_QUEUE","COPYING","FINISHED","ERRORED")
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
    #print('grs1', date)
    assert re.match(r"[\d]{4}-[\d]{2}-[\d]{2}", date)
    #print('grs2', streamer, allStreamersWithVideos)
    assert streamer in allStreamersWithVideos
    key = f"{streamer}|{date}"
    renderStatusLock.acquire()
    status = renderStatuses[key] if key in renderStatuses.keys() else None
    renderStatusLock.release()
    return status
def scanForExistingVideos():
    for file in (f for f in os.listdir(os.path.join(basepath, outputDirectory, "S1")) if f.endswith('.mkv') and not f.endswith('.temp.mkv')):
        fullpath = os.path.join(basepath, outputDirectory, "S1")
        nameparts = file.split(' - ')
        assert len(nameparts) == 3 #and nameparts[0] == outputDirectory
        date = nameparts[1]
        streamerAndExt = nameparts[2]
        parts = streamerAndExt.split('.')
        if any((part=='temp' for part in parts)):
            continue # temp file, ignore
        streamer = parts[0].split(' ')[0] #streamer name will never have a space, so anything can be added between the streamer name and the extension and be ignored
        print(f"Scanned streamer {streamer} and date {date} from file {file}")
        if streamer in allStreamersWithVideos:
            setRenderStatus(streamer, date, 'FINISHED')
        else:
            print(f"Streamer {streamer} not known")

if COPY_FILES:
    activeCopyTask = None
def copyWorker():
    while True:
        if copyQueue.empty():
            print("Copy queue empty, sleeping")
            ttime.sleep(20)
            continue
            #return
        task = copyQueue.get(block=False)
        assert getRenderStatus(task.mainStreamer, task.fileDate) == 'COPY_QUEUE'
        activeCopyTask = task
        setRenderStatus(task.mainStreamer, task.fileDate, 'COPYING')
        #renderCommand = list(task.commandArray)
        for file in task.sourceFiles:
            remotePath = file.videoFile
            localPath = remotePath.replace(basepath, localBasepath)
            if not os.path.isfile(localPath):
                #ttime.sleep(5)
                print(f"Copying file {remotePath} to local storage")
                shutil.copyfile(remotePath, localPath+'.temp') #copy to temp file to avoid tripping the if condition with incomplete transfers
                print('file copy complete')
                shutil.move(localPath+'.temp', localPath)
            else:
                print('local file already exists')
            incrFileRefCount(localPath)
            #copy file and update SourceFile object
            file.localVideoPath = localPath
            #add copied file to filesBySourceVideoPath
            filesBySourceVideoPath[localPath] = file
            #replace file path in renderCommand
            for command in task.commandArray:
                renderCommand[renderCommand.index(remotePath)] = localPath
        renderQueue.put(QueueItem(renderCommand, task.mainStreamer, task.fileDate))
        setRenderStatus(task.mainStreamer, task.fileDate, 'RENDER_QUEUE')

activeRenderTask = None
activeRenderSubprocess = None
def renderWorker(stats_period=30): #30 seconds between encoding stats printing
    while True:
        if renderQueue.empty():
            print("Render queue empty, sleeping")
            ttime.sleep(20)
            continue
        task = renderQueue.get(block=False)
        print(task.commandArray)
        assert getRenderStatus(task.mainStreamer, task.fileDate) == 'RENDER_QUEUE'
        activeRenderTask = task
        renderCommands = list(task.commandArray)
        outpath = renderCommands[-1][-1]
        #pathSplitIndex = outpath.rindex('.')
        #tempOutpath = outpath[:pathSplitIndex]+'.temp'+outpath[pathSplitIndex:]
        tempOutpath = insertSuffix(outpath, '.temp')
        print(outpath, tempOutpath)
        renderCommand[-1][-1] = tempOutpath # output to temp file, so final filename will always be a complete file
        for i in range(len(renderCommands)):
            renderCommands[i].insert(-1, "-stats_period")
            renderCommands[i].insert(-1, str(stats_period))
            renderCommands[i].insert(-1, '-y') # overwrite temp file if it exists
        setRenderStatus(task.mainStreamer, task.fileDate, 'RENDERING')
        hasError = False
        for i in range(len(renderCommands)):
            with open(os.path.join(logFolder, f"{task.mainStreamer}_{task.fileDate}{'' if len(renderCommand)==1 else f'_{i}'}.log",'a')) as logFile:
                print(f"Running render to file {outpath}")
                result = subprocess.run(renderCommand[i], stdout=logFile, stderr=subprocess.STDOUT)
                process = subprocess.Popen(renderCommand[i], stdout=logFile, stderr=subprocess.STDOUT)
                if result.returncode != 0:
                    hasError = True
                    setRenderStatus(task.mainStreamer, task.fileDate, 'ERRORED')
                    with open(errorFilePath, 'a') as errorFile:
                        errorFile.write(' ;; '.join((formatCommand(renderCommand) for renderCommand in renderCommands)))
                    break
                #result = types.SimpleNamespace()
                #result.returncode = 0
                #ttime.sleep(15)
        #except KeyboardInterrupt as ki:
        #    print("Caught keyboard interrupt, reraising")
        #    raise KeyboardInterrupt(ki)
        
        if not hasError:
            count = 1
            suffix = ""
            while os.path.isfile(insertSuffix(outpath, suffix)):
                suffix = f" ({count})"
                count += 1
            shutil.move(tempOutpath, insertSuffix(outpath))
            setRenderStatus(task.mainStreamer, task.fileDate, 'FINISHED')
            if COPY_FILES:
                for file in (f for f in task.sourceFiles if f.videoFile.startswith(localBasepath)):
                    remainingRefs = decrFileRefCount(file.localVideoPath)
                    if remainingRefs == 0:
                        print(f"Removing local file {file}")
                        os.remove(file)
            for file in task.intermediateFiles:
                print(f"Removing intermediate file {file}")
                assert basepath not in file
                #os.remove(file)

def getAllStreamingDaysByStreamer():
    daysByStreamer = {}
    for streamer in sorted(allFilesByStreamer.keys()):
        days = set()
        for file in allFilesByStreamer[streamer]:
            chapters = file.infoJson['chapters']
            fileStartTimestamp = file.startTimestamp
            for chapter in chapters:
                startTime = datetime.fromtimestamp(fileStartTimestamp+chapter['start_time'], LOCAL_TIMEZONE)
                startDate = datetime.strftime(startTime, "%Y-%m-%d")
                days.add(startDate)
                #endTime = datetime.fromtimestamp(fileStartTimestamp+chapter['end_time'], LOCAL_TIMEZONE)
                #endDate = datetime.strftime(endTime, "%Y-%m-%d")
                #days.add(endDate)
        daysByStreamer[streamer]=list(days)
        daysByStreamer[streamer].sort(reverse=True)
    return daysByStreamer

minimumSessionWorkerDelay = timedelta(hours=4)

DEFAULT_MONITOR_STREAMERS = ('ChilledChaos', )


def sessionWorker(monitorStreamers=DEFAULT_MONITOR_STREAMERS, 
                  maxLookback:timedelta=DEFAULT_MAX_LOOKBACK, 
                  dataFilepath=DEFAULT_DATA_FILEPATH,
                  drawLabels=False,
                  startTimeMode='mainSessionStart',
                  endTimeMode='mainSessionEnd',
                  logLevel=1, #max logLevel = 4
                  sessionTrimLookback=1,
                  cutMode='chunked',
                  encodingSpeedPreset='medium',
                  minimumTimeInVideo=450):
    if len(allFilesByVideoId) == 0:
        loadFiledata(dataFilepath)
    scanForExistingVideos()
    #while True:
    oldFileCount = len(allFilesByVideoId)
    scanFiles()
    newFileCount = len(allFilesByVideoId)
    if oldFileCount != newFileCount:
        saveFiledata(dataFilepath)
    latestDownloadTime = max((x.downloadTime for x in allFilesByVideoId.values()))
    currentTime = datetime.now(timezone.utc)
    print(currentTime, latestDownloadTime)
    timeSinceLastDownload = currentTime - latestDownloadTime
    print(timeSinceLastDownload)
    if timeSinceLastDownload > minimumSessionWorkerDelay:
        streamingDays = getAllStreamingDaysByStreamer()
        for streamer in monitorStreamers:
            allDays = streamingDays[streamer] #already sorted with the newest first
            print(streamer, allDays)
            for day in allDays:
                dt = convertToDatetime(day)
                if maxLookback is not None and datetime.now() - dt > maxLookback:
                    print("Reached max lookback, stopping")
                    break
                status = getRenderStatus(streamer, day)
                print(day, status)
                if status is None:
                    #new file, build command and add to queue
                    outPath = getVideoOutputPath(streamer, day)
                    command = generateTilingCommandMultiSegment(streamer, day, outPath,
                                                                drawLabels=drawLabels,
                                                                startTimeMode=startTimeMode,
                                                                endTimeMode=endTimeMode,
                                                                logLevel=logLevel,
                                                                cutMode=cutMode,
                                                                sessionTrimLookback=sessionTrimLookback,
                                                                encodingSpeedPreset=encodingSpeedPreset,
                                                                minimumTimeInVideo=minimumTimeInVideo)
                    if command is None: #command cannot be made, maybe solo stream or only one 
                        continue
                    item = QueueItem(command, streamer, day)
                    print(f"Adding render for streamer {streamer} from {day}")
                    (copyQueue if COPY_FILES else renderQueue).put(item)
                    setRenderStatus(streamer, day, "COPY_QUEUE" if COPY_FILES else "RENDER_QUEUE")
                    #break #
                elif maxLookback is None:
                    print("Reached last rendered date for streamer, stopping\n")
                    break
    else:
        print("Files are too new, waiting longer...")
        #ttime.sleep(60*60)#*24)

commandArray = []
class Command:
    def __init__(self, targetFunc, description):
        self.targetFunc = targetFunc
        self.description = description

def endRendersAndExit():
    print('Shutting down...')
    if activeRenderSubprocess is not None:
        activeRenderSubprocess.terminate()
        activeRenderSubprocess.wait(3)
        if activeRenderSubprocess.poll is None:
            activeRenderSubprocess.kill()
            activeRenderSubprocess.wait()
    sys.exit(0)
commandArray.append(Command(sys.exit, 'Exit program'))
def printActiveJobs():
    print(f"Active render job:", "None" if activeRenderTask is None else f"{str(activeRenderTask)}")
    if COPY_FILES:
        print(f"Active copy job:", "None" if activeCopyTask is None else f"{str(activeCopyTask)}")
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

def commandWorker():
    while True:
        for _ in range(5):
            print()
        for i in range(len(commandArray)):
            command = commandArray[i]
            print(f"{str(i)}. {command.description}")
        #print("\n\n\n\n\n\n0. Exit program\n1. Print active jobs\n2. Print queued jobs\n3. Manually add job\n4. Modify/rerun job\n")
        userInput = input(" >> ")
        if not userInput.isdigit():
            print(f"Invalid input: '{userInput}'")
            print("Please try again")
            continue
        optionNum = int(userInput)
        if optionNum < 0 or optionNum > len(commandArray):
            print(f"Invalid option number: {userInput}")
            print("Please try again")
        commandArray[optionNum].targetFunc()
        raise Exception("Not implemented yet")
        

if __name__=='__main__': 
    if COPY_FILES:
        copyThread = threading.Thread(target=copyWorker)
        #copyThread.start()
    renderThread = threading.Thread(target=renderWorker)
    #renderThread.start()
    sessionThread = threading.Thread(target=sessionWorker, kwargs={'drawLabels':False,
                                                                   'startTimeMode':'mainSessionStart',
                                                                   'endTimeMode':'mainSessionEnd',
                                                                   'logLevel':3,
                                                                   'sessionTrimLookback':1,
                                                                   'maxLookback':timedelta(days=14),
                                                                  })
    #sessionThread.start()

    #sessionWorker(maxLookback=timedelta(days=7,hours=18), logLevel=2)
    #copyWorker()
    #print(getAllStreamingDaysByStreamer()['ChilledChaos'])
    commandWorker()
    allGames = calcGameCounts()
    for game in sorted(allGames.keys(), key=lambda x: (allGames[x], x)):
        print(game, allGames[game])
    del allGames

# %%
os.cpu_count()

# %%
str(renderQueue.queue)

# %% [markdown]
# renderThread.start()

# %%
print(renderStatuses)

# %%
gameAliases = {'Among Us':('Town of Us', r"TOWN OF US PROXY CHAT | Among Us w/ Friends"),
               'Tabletop Simulator': ('Board Games',),
               'Suika Game': ('Suika',),
               'Monopoly Plus': ('Monopoly',)}

def normalizeAllGames():
    gameCounts = calcGameCounts()
    pprint(gameCounts)
    knownReplacements = {}
    lowercaseGames = {}
    for game, alias in gameAliases.items():
        assert game.lower() not in lowercaseGames.keys()
        knownReplacements[game] = list(alias)
        lowercaseGames[game.lower()] = game
    for game in gameCounts.keys():
        #if gameCounts[game] == 1:
        #    continue
        trueGame = None
        for key in knownReplacements.keys():
            if any((game == alias for alias in knownReplacements[key])):
                trueGame = key
                break
        if trueGame is None:
            trueGame = game
        else:
            print(game, trueGame)
            continue
            
        #if any((any((game == alias for alias in knownReplacements[key])) for key in knownReplacements.keys())):
            #game is already a known alias
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
                raise Exception(f"Two capitalizations have the same count, cannot determine which is correct: {game}; {altgame}")
        #else:
        elif gameCounts[game] > 1:
            knownReplacements[game] = []
            lowercaseGames[lowergame] = game
    
    pprint(knownReplacements, width=200)
    for game in (game for game in gameCounts.keys() if gameCounts[game]==1):
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
            print(game, matches)
            #longestIndex = 0
            #for index in range(1, len(matches)):
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
            longestMatch = sorted(matches, key=lambda x:(0-locateIndex(x), len(x)))[-1]
            #longestMatch = sorted(matches, key=lambda x:(game.lower().index(x.lower()), len(x)))[-1]
            #assert len(matches) == 1
            knownReplacements[longestMatch].append(game)
    for key in list(knownReplacements.keys()):
        if len(knownReplacements[key])==0:
            del knownReplacements[key]
    pprint(knownReplacements, width=200)
    def normalizeGame(originalGame:str):
        for game, aliases in knownReplacements.items():
            if originalGame == game or originalGame in aliases:
                return game
    for streamer, sessions in allStreamerSessions.items():
        print(f"Normalizing games for streamer {streamer}")
        for session in sessions:
            ...

normalizeAllGames()

# %% [markdown]
# # tileResolutionsV1 = [None,"1920:1080", "1920:1080", "1280:720", "960:540", "768:432", "640:360", "640:360"]
# outputResolutionsV1 = [None, "1920:1080", "3840:1080", "3840:2160", "3840:2160", "3840:2160", "3840:2160", "4480:2520"]
#
# def generateTilingFiltergraphSingleSegment(startTimes:list, duration):
#     numTiles = len(startTimes)
#     if numTiles < 2:
#         raise Exception("Too few tiles")
#     #elif numTiles == 2:
#     #    return "[0:v][1:v]hstack=inputs=2[v]"
#     tileWidth = calcTileWidth(numTiles)
#     scale = tileResolutionsV1[tileWidth]
#     filters = [f"[{n}:v] trim={startTimes[n]}:{startTimes[n]+duration}, setpts={vpts}, scale={scale}:force_original_aspect_ratio=decrease:eval=frame,pad={scale}:-1:-1:color=black [V{n}]" for n in range(numTiles)]
#     def generateLayout():
#         def generateLE(tileNum): # generateLayoutElement
#             x = tileNum % tileWidth
#             y = tileNum // tileWidth
#             def generateLEC(coord, letter): # generateLayoutElementComponent
#                 if coord == 0:
#                     return "0"
#                 return "+".join([f"{letter}{n}" for n in range(coord)])
#             return f"{generateLEC(x,'w')}_{generateLEC(y,'h')}"
#         return "|".join([generateLE(n) for n in range(numTiles)])
#     filters.append(f"[{']['.join([f'V{n}' for n in range(numTiles)])}]{'x' if numTiles>2 else 'h'}stack=inputs={numTiles}:{generateLayout()}{':fill=black' if tileWidth**2!=numTiles else ''}[vout]")
#     filters.extend([f"[{n}:a] atrim={startTimes[n]}:{startTimes[n]+duration}, asetpts={apts} [A{n}]" for n in range(numTiles)])
#     return ";".join(filters)
#
# def generateTilingCommandSingleSegment(inputFilesAndTimes, outputfile, duration):
#     numTiles = len(inputFilesAndTimes)
#     if numTiles < 2:
#         raise Exception("Too few tiles")
#     inputOptions = reduce(list.__add__, [['-i', file] for file, _ in inputFilesAndTimes])
#     streamMappings = reduce(list.__add__, [["-map", f"[A{n}]"] for n in range(len(inputFilesAndTimes))])
#     fullOptions = reduce(list.__add__, [["ffmpeg"],
#         inputOptions,
#         ['-filter_complex', generateTilingFiltergraphSingleSegment([x[1] for x in inputFilesAndTimes], duration), '-map', '[vout]'],
#         streamMappings,
#         ["-c:v","libx264","-s", "3840x2160" if numTiles > 2 else "3840x1080", outputfile]])
#     return fullOptions
#
#
# #print(generateTilingFiltergraphSingleSegment([15.321,6754.825,7.129], 30))
# print(generateTilingCommandSingleSegment([['/inputs/video1.mp4', 15.321], ['/inputs/video2.mp4',6754.825], ['/inputs/video3.mp4',7.129]], '/segments/segment1.mkv', 30))

# %% [markdown]
# mainStreamerSessions = []
# for streamer in mainStreamers:
#     streamerPath = os.path.join(basepath,streamer,'S1')
#     for filename in sorted(os.listdir(streamerPath)):
#         filepath = os.path.join(streamerPath, filename)
#         if os.path.isfile(filepath) and filename.endswith('info.json'):
#             with open(filepath) as file:
#                 infodict = json.load(file)
#             starttime = infodict['timestamp']
#             chapters = infodict['chapters']
#             #print(starttime, chapters)
#             for chapter in chapters:
#                 chapterstart = int(starttime + chapter['start_time'])
#                 chapterend = int(starttime + chapter['end_time'])
#                 if chapterstart != chapterend:
#                     game = chapter['title']
#                     print(chapterstart, chapterend, game, streamer, sep=' ;; ')
#                     mainStreamerSessions.append({
#                         'start':chapterstart,
#                         'end':chapterend,
#                         'title':game,
#                         'streamer':streamer
#                     })
#                     mainStreamerSesions
#
# def titlesMatch(title1, title2):
#     return title1.lower() == title2.lower()
#
# def calculateOverlap(start1:int|float, end1:int|float, start2:int|float, end2:int|float):
#     overlapStart = max(start1, start2)
#     overlapEnd = min(end1, end2)
#     overlapLength = overlapEnd - overlapStart
#     shorterLength = min(end1-start1, end2-start2)
#     return overlapLength / float(shorterLength)
#
# secondarySessions={}
# def toKey(start,end,title, streamer):
#     return f"{streamer}-{start}-{end}-{title}"
# def addSecondarySession(key,value):
#     if key not in secondarySessions:
#         secondarySessions[key] = [value]
#     else:
#         secondarySessions[key].append(value)
# for streamer in secondaryStreamers:
#     streamerPath = os.path.join(basepath, streamer, 'S1')
#     for filename in os.listdir(streamerPath):
#         filepath = os.path.join(streamerPath, filename)
#         if os.path.isfile(filepath) and filename.endswith('info.json'):
#             with open(filepath) as file:
#                 infodict = json.load(file)
#             starttime = infodict['timestamp']
#             chapters = infodict['chapters']
#             #print(starttime, chapters)
#             for chapter in chapters:
#                 chapterstart = int(starttime + chapter['start_time'])
#                 chapterend = int(starttime + chapter['end_time'])
#                 if chapterstart != chapterend:
#                     game = chapter['title']
#                     print(chapterstart, chapterend, game, streamer, sep=' ;; ')
#                     for mainSession in (x for x in mainStreamerSessions if titlesMatch(x['title'], game)):
#                         if mainSession['start'] <= chapterend and mainSession['end'] >= chapterstart:
#                             key = toKey(mainSession['start'], mainSession['end'], mainSession['title'], mainSession['streamer'])
#                             try:
#                                 addSecondarySession(key, {'start':chapterstart, 'end':chapterend, 'title':game,'streamer':streamer,
#                                                  'overlap':calculateOverlap(mainSession['start'], mainSession['end'],
#                                                                            chapterstart, chapterend)})
#                             except Exception as ex:
#                                 print(mainSession)
#                                 print(chapter)
#                                 raise ex

# %% [markdown]
# print([[key, value]#[x for x in value if x['overlap']>=0.8]]
#        for key, value
#        in secondarySessions.items()
#        if key.endswith('Among Us')])

# %% [markdown]
# import os, subprocess, json
#
# properties = {}
#
# ignoredProperties = set()
#
# def addProperty(name, value):
#     if name in ignoredProperties:
#         return
#     if name not in properties.keys():
#         properties[name] = set()
#     if len(properties[name]) > 100:
#         ignoredProperties.add(name)
#         print(f"Adding {name} to the ignored properties list")
#         del properties[name]
#         return
#     try:
#         properties[name].add(value)
#     except TypeError:
#         print(f"Property {name} is an unhashable type, ignoring")
#         ignoredProperties.add(name)
#         del properties[name]
#
# def getVideoFileProperties(filepath):
#     assert os.path.isabs(filepath)
#     cproc = subprocess.run(['ffprobe', '-show_streams', '-of', 'json', '-i', filepath], capture_output=True)
#     result = cproc.stdout.decode()
#     parsed = json.loads(result)
#     return parsed
#
# for root, dirs, files in os.walk("/mnt/pool2/media/Twitch Downloads/"):
#     for file in sorted(os.path.join(root, x) for x in files if x[-4:] in (".mp4", ".mkv"))[:5]:
#         print(file)
#         cproc = subprocess.run(['ffprobe', '-show_streams', '-of', 'json', '-i', file], capture_output=True)
#         result = cproc.stdout.decode()
#         parsed = json.loads(result)
#         #print(result)
#         #print(parsed)
#         try:
#             streams = parsed['streams']
#             video_streams = [x for x in streams if x['codec_type'] == "video"]
#             assert len(video_streams) == 1
#             video_info = video_streams[0]
#             for key in video_info.keys():
#                 addProperty(key, video_info[key])
#             print(video_info['width'], video_info['height'])#, video_info, sep="\n", end="\n\n\n\n")
#             #print(properties)
#         except Exception as e:
#             print(result)
#             raise e
# print(properties)

# %% [markdown]
# #[[0,0,1920,1080]],
# #[[0,0,1920,1080],[1920,0,3840,1080]],
# #[[0,0,1920,1080],[1920,0,3840,1080],
# # [960,1080,2880,2160]],
# #[[0,0,1920,1080],[1920,0,3840,1080],
# # [0,1080,1920,2160],[1920,1080,3840,2160]],
# #[[0,0,1280,720],[1280,0,2560,720],[2560,0,3840,720],
# # [640,720,1920,1440],[1920,720,3200,1440]],
# #[[0,0,1280,720],[1280,0,2560,720],[2560,0,3840,720],
# # [0,720,1280,1440],[1280,720,2560,1440],[2560,720,3840,1440]],
# #[[0,0,1280,720],[1280,0,2560,720],[2560,0,3840,720],
# # [0,720,1280,1440],[1280,720,2560,1440],[2560,720,3840,1440],
# # [1280,1440,2560,2160]],
# #[[0,0,1280,720],[1280,0,2560,720],[2560,0,3840,720],
# # [0,720,1280,1440],[1280,720,2560,1440],[2560,720,3840,1440],
# # [640,1440,1920,2160],[1920,1440,3200,2160]],
# #[[0,0,1280,720],[1280,0,2560,720],[2560,0,3840,720],
# # [0,720,1280,1440],[1280,720,2560,1440],[2560,720,3840,1440],
# # [0,1440,1280,2160],[1280,1440,2560,2160],[2560,1440,3840,2160]]
