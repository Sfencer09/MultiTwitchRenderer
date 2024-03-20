
from typing import Dict, List, Tuple
import os
import math
import random
import sys

from datetime import datetime, timedelta
from functools import reduce, partial
from pprint import pprint
from Session import Session

print = partial(print, flush=True)

print(sys.executable)
sys.path.append(os.path.dirname(sys.executable))

if __debug__:
    from config import *
exec(open("config.py").read(), globals())

import scanned

from SourceFile import SourceFile
from ParsedChat import convertToDatetime
from RenderConfig import RenderConfig, ACTIVE_HWACCEL_VALUES, HW_DECODE, HW_INPUT_SCALE, HW_OUTPUT_SCALE, HW_ENCODE
from SharedUtils import calcGameCounts, getVideoOutputPath

print("Starting")


def calcTileWidth(numTiles):
    return int(math.sqrt(numTiles-1.0))+1

# 0: Build filesets for lookup and looping; pair video files with their info files (and chat files if present)


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


def generateTilingCommandMultiSegment(mainStreamer, targetDate, renderConfig=RenderConfig(), outputFile=None) -> List[List[str]]:
    otherStreamers = [
        name for name in scanned.allStreamersWithVideos if name != mainStreamer]
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
    preciseAlign = renderConfig.preciseAlign
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
        x.startTimestamp, tz=UTC_TIMEZONE) <= targetDateEndTime, scanned.allStreamerSessions[mainStreamer]))
    if len(mainSessionsOnTargetDate) == 0:
        raise ValueError(
            "Selected streamer does not have any sessions on the target date")
    mainSessionsOnTargetDate.sort(key=lambda x: x.startTimestamp)
    if logLevel >= 1:
        print("\n\n\nStep 2: ", targetDateStartTime, targetDateEndTime)
        if logLevel >= 2:
            pprint(mainSessionsOnTargetDate)

    #groupsFromMainFiles = reduce(list.append,  # list.__add__,
    #                             (file.parsedChat.groups for file in set((session.file for session in mainSessionsOnTargetDate)
    #                                                                     ) if file.parsedChat is not None), [])
    groupsFromMainFiles = []
    for file in set((session.file for session in mainSessionsOnTargetDate)):
        if file.parsedChat is not None:
            groupsFromMainFiles.extend(file.parsedChat.groups)
    
    mainFiles = set((session.file for session in mainSessionsOnTargetDate))
    if logLevel >= 1:
        print("\n\nStep 2.1: ")
        pprint(groupsFromMainFiles)

        for mainFile in mainFiles:
            print(mainFile.infoFile)
            chat = mainFile.parsedChat
            if chat is not None:
                pprint(chat.groups)

    # 3. For all other streamers, build a sorted array of sessions that have matching games & have time overlap (and/or
        # appear in a !who-type command during that time if rechat is found)
    secondarySessionsArray:List[Session] = []
    inputSessionsByStreamer = {}
    inputSessionsByStreamer[mainStreamer] = mainSessionsOnTargetDate
    for streamer in scanned.allStreamerSessions.keys():
        if streamer == mainStreamer:
            continue
        inputSessionsByStreamer[streamer] = []
        for session in scanned.allStreamerSessions[streamer]:
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
    segmentFileMatrix:List[List[None|SourceFile]] = [[None for i in range(
        len(allInputStreamers))] for j in range(numSegments)]
    segmentSessionMatrix:List[List[None|List[Session]]] = [[None for i in range(
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
                                missingSessions = [session for session in scanned.allStreamerSessions[streamer]
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
    inputFilesSorted:List[SourceFile] = sorted(set([item for sublist in segmentFileMatrix for item in sublist if item is not None]),
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
    timeFilter = f"setpts=PTS-STARTPTS"

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
                    videoFiltergraph = f"[{inputVSegName}] setpts=PTS-STARTPTS{uploadFilter}{scaleFilter}{padFilter}{downloadFilter}{labelFilter} [{outputVSegName}]"
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
                    audioFiltergraph = f"[{inputIndex}:a] atrim={startOffset}:{endOffset}, asetpts=PTS-STARTPTS [{audioSegmentName}]"
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
        fileOffsets:Dict[str, Dict[str, float]] = {}
        if preciseAlign:
            import AudioAlignment
            measurements:Dict[str, Dict[str, List[int, int]]] = {}
            for rowNum, row in enumerate(segmentFileMatrix):
                primaryFile = row[0]
                if primaryFile is None:
                    continue
                primaryVideoPath = primaryFile.localVideoFile if primaryFile.localVideoFile is not None else primaryFile.videoFile
                if primaryVideoPath not in measurements:
                    measurements[primaryVideoPath] = {}
                currentMeasurements = measurements[primaryVideoPath]
                segmentStartTime = uniqueTimestampsSorted[rowNum]
                segmentEndTime = uniqueTimestampsSorted[rowNum+1]
                segmentDuration = segmentEndTime - segmentStartTime
                for f in row[1:]:
                    if f is not None:
                        secondaryVideoPath = f.localVideoFile if f.localVideoFile is not None else f.videoFile
                        if primaryVideoPath in fileOffsets and secondaryVideoPath in fileOffsets[primaryVideoPath]:
                            continue
                        streamOverlapStart = max(f.startTimestamp, primaryFile.startTimestamp)
                        streamOffsetStart = segmentStartTime - streamOverlapStart
                        streamOffsetEnd = segmentEndTime - streamOverlapStart
                        if secondaryVideoPath not in currentMeasurements:
                            currentMeasurements[secondaryVideoPath] = [streamOffsetStart, streamOffsetEnd]
                        else:
                            #assert currentMeasurements[secondaryVideoPath][1] == streamOffsetStart, f"{currentMeasurements[secondaryVideoPath]} != {streamOffsetStart}"
                            assert currentMeasurements[secondaryVideoPath][1] <= streamOffsetStart
                            currentMeasurements[secondaryVideoPath][1] = streamOffsetEnd
            for primaryFilePath, secondaryFilePaths in measurements.items():
                if primaryFilePath not in fileOffsets:
                    fileOffsets[primaryFilePath] = {}
                currentFileOffsets = fileOffsets[primaryFilePath]
                for secondaryFilePath, searchOffsets in secondaryFilePaths.items():
                    if secondaryFilePath not in currentFileOffsets:
                        startOffset, endOffset = searchOffsets
                        streamOffset = scanned.filesBySourceVideoPath[secondaryFilePath].startTimestamp - \
                            scanned.filesBySourceVideoPath[primaryFilePath].startTimestamp
                        audioOffset = AudioAlignment.findAverageAudioOffset(primaryFilePath,
                                                                            secondaryFilePath,
                                                                            initialOffset=streamOffset,
                                                                            start=startOffset,
                                                                            duration = min(AudioAlignment.MAX_LOAD_DURATION, endOffset - startOffset),
                                                                            macroWindowSize = 10*60,
                                                                            macroStride = 10*60,
                                                                            microWindowSize = 10)
                        if audioOffset is not None:
                            currentFileOffsets[secondaryFilePath] = audioOffset

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
            rowMainFile = segmentFileMatrix[segIndex][0]
            if rowMainFile is not None:
                rowMainFilePath = rowMainFile.localVideoFile if rowMainFile.localVideoFile is not None else rowMainFile.videoFile
                if rowMainFilePath in fileOffsets:
                    rowFileOffsets = fileOffsets[rowMainFilePath]
                else:
                    rowFileOffsets = {}
            else:
                rowFileOffsets = {}
            rowInputOptions = []
            for streamerIndex in range(len(allInputStreamers)):
                file = segmentFileMatrix[segIndex][streamerIndex]
                videoSegmentName = f"seg{segIndex}V{streamerIndex}"
                audioSegmentName = f"seg{segIndex}A{streamerIndex}"
                # 13b. Use #10a&b and #9a to build intermediate segments
                if file is not None:
                    startOffset = segmentStartTime - file.startTimestamp
                    fileVideoPath = file.localVideoFile if file.localVideoFile is not None else file.videoFile
                    if fileVideoPath in rowFileOffsets:
                        #early compared to main streamer = positive offset
                        startOffset -= rowFileOffsets[fileVideoPath]
                    #endOffset = segmentEndTime - file.startTimestamp
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
                    rowInputOptions.extend(('-i', fileVideoPath))
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
                        print("\n\nStep 13b: ", segIndex, streamerIndex, file, startOffset, #endOffset, 
                              inputIndex, streamerIndex, videoSegmentName, audioSegmentName)
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


def normalizeAllGamesV2():
    gameCounts = calcGameCounts()
    pprint(gameCounts)
    print("\n\n\n---------------------------------------------------------------\n\n\n")
    replacements = {}
