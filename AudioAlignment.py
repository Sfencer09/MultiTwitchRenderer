from math import ceil
import time
from typing import Dict, List, Tuple
import librosa
import numpy as np
from scipy import signal
import os
import sys
import psutil
import subprocess
import warnings
warnings.filterwarnings('ignore')

import MTRLogging
logger = MTRLogging.getLogger('AudioAlignment')

from SharedUtils import insertSuffix
from SourceFile import SourceFile

sys.path.append(os.path.dirname(sys.executable))

if __debug__:
    from config import *
exec(open("config.py").read(), globals())

audioFiles = set()
audioExt = ".m4a"
audioBasepath = os.path.join(localBasepath, "extracted-audio")
os.makedirs(audioBasepath, exist_ok=True)


def getAudioPath(videoPath: str):
    # assert any((videoPath.endswith(videoExt) for videoExt in videoExts))
    assert videoPath.startswith(basepath)
    for videoExt in videoExts:
        if videoPath.endswith(videoExt):
            return (
                os.path.join(audioBasepath, videoPath.replace(basepath, ""))[
                    : -len(videoExt)
                ]
                + audioExt
            )
    raise ValueError("Must be a video file")


def readExistingAudioFiles():
    for root, _, files in os.walk(audioBasepath):
        for file in [os.path.join(root, file) for file in files]:
            if os.path.getatime(file) < time.time() - 7 * (24 * 60 * 60):
                os.remove(file)
            else:
                audioFiles.add(file)
    logger.detail(audioFiles)


readExistingAudioFiles()


def extractAudio(target_file: str):
    audioPath = getAudioPath(target_file)
    if audioPath not in audioFiles:
        os.makedirs(os.path.dirname(audioPath), exist_ok=True)
        extractCommand = [
            ffmpegPath + "ffmpeg",
            "-i",
            target_file,
            "-vn",
            "-acodec",
            "copy",
            "-y",
            audioPath,
        ]
        subprocess.check_call(extractCommand, stderr=subprocess.PIPE, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        audioFiles.add(audioPath)
    return audioPath


__DEFAULT_DURATION = None  # 3600
__DEFAULT_WINDOW = None
""" 
import matplotlib.pyplot as plt

def findAudioOffset(
    within_file: str,
    find_file: str,
    offset: float = 0,
    duration: float | None = __DEFAULT_DURATION,
    #window: float | None = __DEFAULT_WINDOW,
    start: float = 0,
):
    withinAudioFile = extractAudio(within_file)
    findAudioFile = extractAudio(find_file)
    print("Audio extracted, memory tuple:", psutil.virtual_memory())
    y_within, sr_within = librosa.load(
        withinAudioFile,
        sr=None,
        offset=start + (offset if offset > 0 else 0),
        duration=duration,
    )
    print("First audio loaded, memory tuple:", psutil.virtual_memory())
    y_find, _ = librosa.load(
        findAudioFile,
        sr=sr_within,
        offset=start - (offset if offset < 0 else 0),
        #duration=window if window is not None else duration,
        duration=duration,
    )
    print("Second audio loaded, memory tuple:", psutil.virtual_memory())
    # if window is not None:
    #    c = signal.correlate(
    #        y_within, y_find[:sr_within*window], mode='valid', method='fft')
    # else:
    c = signal.correlate(y_within, y_find, mode="full", method="fft")
    print("Signal correlated, memory tuple:", psutil.virtual_memory())
    peak = np.argmax(c)
    offset = round(peak / sr_within, 2)

    print(f"Max peak found at {str(offset)}, writing plot")
    fig, ax = plt.subplots()
    ax.plot(c)
    suffix = ""
    count = 0
    imagePath = "/mnt/pool2/media/Twitch Downloads/cross-correlation.png"
    while os.path.isfile(insertSuffix(imagePath, suffix)):
        suffix = f" ({count})"
        count += 1
    finalImagePath = insertSuffix(imagePath, suffix)
    print(
        f"Writing plot to {finalImagePath}, memory tuple:", psutil.virtual_memory())
    fig.savefig(finalImagePath)

    return offset """

def histogramByBucket(arr, bucketSize = 10):
    ...

MAX_LOAD_DURATION = 7200

DEFAULT_MACRO_WINDOW_SIZE: int = 600
DEFAULT_MICRO_WINDOW_SIZE: int = 10
DEFAULT_BUCKET_SIZE: float | int = 1
DEFAULT_BUCKET_SPILLOVER: int = 1

def findAudioOffsets(within_file: str,
    find_file: str,
    initialOffset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = DEFAULT_MACRO_WINDOW_SIZE,
    macroStride: int | None = None,
    microWindowSize: int = DEFAULT_MICRO_WINDOW_SIZE,
    microStride: float | int | None = None,
    bucketSize: float | int = DEFAULT_BUCKET_SIZE,
    bucketSpillover: int = DEFAULT_BUCKET_SPILLOVER,
    ):
    startTime = time.time()
    if macroWindowSize < 5 * microWindowSize:
        raise ValueError("macroWindowSize should be at least five times microWindowSize for good results")
    if macroWindowSize < 60 * 10:
        raise ValueError("macroWindowSize must be at least 10 minutes")
    if macroStride is None:
        macroStride = macroWindowSize #// 2
    if microStride is None:
        microStride = microWindowSize / 2
    withinAudioFile = extractAudio(within_file)
    findAudioFile = extractAudio(find_file)
    logger.info(f"{withinAudioFile}, {findAudioFile}")
    logger.debug(f"Audio extracted in {round(time.time()-startTime, 2)} seconds, memory tuple: {psutil.virtual_memory()}")
    logger.detail(f"Initial offset = {initialOffset}")
    y_within, sr_within = librosa.load(
        withinAudioFile,
        sr=None,
        offset=start + (initialOffset if initialOffset > 0 else 0),
        duration=duration,
    )
    logger.detail(f"First audio loaded in {round(time.time()-startTime, 2)} seconds, memory tuple: {psutil.virtual_memory()}")
    startTime = time.time()
    y_find, _ = librosa.load(
        findAudioFile,
        sr=sr_within,
        offset=start - (initialOffset if initialOffset < 0 else 0),
        # duration=window if window is not None else duration,
        duration=duration
    )
    logger.detail(f"Second audio loaded in {round(time.time()-startTime, 2)} seconds, memory tuple: {psutil.virtual_memory()}")
    startTime = time.time()
    withinLength = y_within.shape[0] / sr_within
    findLength = y_find.shape[0] / sr_within
    overlapLength = min(withinLength, findLength)
    offsetsFound: Dict[str, List[Tuple[float, float, float]]] = dict()
    threshold = max(100, 5 * microWindowSize) #500
    #allOffsetsFound: Dict[str, List[Tuple[float, float, float]]] = dict()
    allOffsetsFound: List[tuple] = []
    for macroWindowNum in range(int(ceil((overlapLength - macroWindowSize) / macroStride))):
        macroWindowStart = macroWindowNum * macroStride * sr_within
        macroWindowEnd = ((macroWindowNum * macroStride) + macroWindowSize) * sr_within
        logger.debug(f"Macro start: {macroWindowStart/sr_within}, end: {macroWindowEnd/sr_within}")
        withinSnippet = y_within[macroWindowStart : macroWindowEnd]
        for microWindowNum in range(int(ceil((macroWindowSize - microWindowSize) / microStride))):
            microWindowStart = int(macroWindowStart + (microWindowNum * microStride * sr_within))
            microWindowEnd = int(macroWindowStart + (((microWindowNum * microStride) + microWindowSize) * sr_within))
            logger.debug(f"Micro start: {microWindowStart/sr_within}, end: {microWindowEnd/sr_within}")
            findSnippet = y_find[microWindowStart:microWindowEnd]
            c = signal.correlate(withinSnippet, findSnippet, mode='same', method='fft')
            logger.debug(f"Signal correlated, memory tuple: {psutil.virtual_memory()}")
            peak = np.argmax(c)
            logger.trace(f"within shape = {withinSnippet.shape}, find shape = {findSnippet.shape}, c shape = {c.shape}")
            foundOffset = round(((peak + macroWindowStart - microWindowStart) / sr_within) - (microWindowSize / 2), 2)
            offsetStr = str(round(foundOffset / bucketSize) * bucketSize)
            offsetEntry = (foundOffset, c[peak], microWindowStart/sr_within)
            if c[peak] >= threshold:
                logger.debug(f"Found offset {foundOffset}, putting in bucket {offsetStr} (peakHeight={c[peak]}, threshold={threshold}, peakTimeInternal={peak/sr_within})")
                if offsetStr in offsetsFound.keys():
                    offsetsFound[offsetStr].append(offsetEntry)
                else:
                    offsetsFound[offsetStr] = [offsetEntry]
            #else:
                #print(f"Found offset {foundOffset} with insufficient peak match (peakHeight={c[peak]}, threshold={threshold}, peakTimeInternal={peak/sr_within})")
            #if offsetStr not in allOffsetsFound.keys():
            #    allOffsetsFound[offsetStr] = [offsetEntry]
            #else:
            #    allOffsetsFound[offsetStr].append(offsetEntry)
            allOffsetsFound.append(offsetEntry)
    logger.info(f"Time = {time.time() - startTime} seconds")
    for offsetFound in offsetsFound.values():
        offsetFound.sort(key=lambda x: x[1])
    logger.trace(offsetsFound)
    #weightedAverageOffset = sum((offset * weight for offset, weight, _ in allOffsetsFound)) / sum((weight for _, weight, _ in allOffsetsFound))
    #print("Weighted average offset:", weightedAverageOffset)
    #print("\n\n\n")
    spilledOffsets: Dict[str, List[Tuple[float, float, float]]] = dict()
    for key in offsetsFound.keys():
        spilledOffsets[key] = list(offsetsFound[key])
        keyInt = float(key)
        for offset in range(1, bucketSpillover+1):
            upOneKey = str(keyInt+(bucketSize*offset))
            downOneKey = str(keyInt-(bucketSize*offset))
            logger.debug(f"{key}, {upOneKey}, {downOneKey}")
            if upOneKey in offsetsFound.keys():
                spilledOffsets[key].extend(offsetsFound[upOneKey])
            if downOneKey in offsetsFound.keys():
                spilledOffsets[key].extend(offsetsFound[downOneKey])
    logger.trace(spilledOffsets)
    return spilledOffsets

def findPopularAudioOffsets(
    within_file: str,
    find_file: str,
    initialOffset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = DEFAULT_MACRO_WINDOW_SIZE,
    macroStride: int | None = None,
    microWindowSize: int = DEFAULT_MICRO_WINDOW_SIZE,
    microStride: float | int | None = None,
    bucketSize: float | int = DEFAULT_BUCKET_SIZE,
    bucketSpillover: int = DEFAULT_BUCKET_SPILLOVER,
    popularThreshold: int = 1, 
):
    allOffsets = findAudioOffsets(within_file=within_file,
                                      find_file=find_file,
                                      initialOffset=initialOffset,
                                      start=start,
                                      duration=duration,
                                      macroWindowSize=macroWindowSize,
                                      macroStride=macroStride,
                                      microWindowSize=microWindowSize,
                                      microStride=microStride,
                                      bucketSize=bucketSize,
                                      bucketSpillover=bucketSpillover,
                                      )
    offsetsByFrequency = sorted(allOffsets.keys(), key=lambda x: -len(allOffsets[x]))
    if len(offsetsByFrequency) == 0:
        return {}
    popularOffsetKeys = [offset for offset in offsetsByFrequency if len(allOffsets[offset]) > popularThreshold]
    logger.debug(f"popularOffsetKeys: {popularOffsetKeys}")
    popularOffsets = {}
    for key in popularOffsetKeys:
        popularOffsets[key] = allOffsets[key]
    return popularOffsets


def findAverageAudioOffset(
    within_file: str,
    find_file: str,
    initialOffset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = DEFAULT_MACRO_WINDOW_SIZE,
    macroStride: int | None = None,
    microWindowSize: int = DEFAULT_MICRO_WINDOW_SIZE,
    microStride: float | int | None = None,
    bucketSize: float | int = DEFAULT_BUCKET_SIZE,
    bucketSpillover: int = DEFAULT_BUCKET_SPILLOVER,
):
    allOffsets = findAudioOffsets(within_file=within_file,
                                      find_file=find_file,
                                      initialOffset=initialOffset,
                                      start=start,
                                      duration=duration,
                                      macroWindowSize=macroWindowSize,
                                      macroStride=macroStride,
                                      microWindowSize=microWindowSize,
                                      microStride=microStride,
                                      bucketSize=bucketSize,
                                      bucketSpillover=bucketSpillover,
                                      )
    if allOffsets is None or len(allOffsets) == 0:
        return None
    offsetsByFrequency = sorted(allOffsets.keys(), key=lambda x: -len(allOffsets[x]))
    logger.trace(f"offsetsByFrequency {offsetsByFrequency}")
    logger.detail(f"offset lengths: {[(key, len(allOffsets[key])) for key in offsetsByFrequency]}")
    reoccurringOffsets = [offset for offset in offsetsByFrequency if len(allOffsets[offset]) > 1]
    logger.debug(f"reoccurringOffsets {reoccurringOffsets}")
    if len(reoccurringOffsets) > 1:
        occurrenceCounts = np.zeros(len(reoccurringOffsets))
        for i in range(len(reoccurringOffsets)):
            occurrenceCounts[i] = len(allOffsets[reoccurringOffsets[i]])
        avg = np.average(occurrenceCounts)
        stddev = np.std(occurrenceCounts)
        logger.debug(f"avg {avg}, stddev {stddev}")
        popularOffsets = [offset for offset in offsetsByFrequency if len(allOffsets[offset]) >= avg+stddev]
        if len(popularOffsets) == 0:
            return None
        logger.debug(f"popularOffsets {popularOffsets}")
        mostPopularOffset = popularOffsets[0]
        if len(popularOffsets) > 1:
            secondMostPopularOffset = popularOffsets[1]
            if len(allOffsets[secondMostPopularOffset]) == len(allOffsets[mostPopularOffset]):
                if abs(float(mostPopularOffset) - float(secondMostPopularOffset)) > bucketSize:
                    return None
                else:
                    raise NotImplementedError
                    assert len(popularOffsets) == 2 or len(allOffsets[popularOffsets[2]]) < len(allOffsets[mostPopularOffset])
                    return None
        #assert len(popularOffsets) <= 1 or len(allOffsets[popularOffsets[1]]) != len(allOffsets[mostPopularOffset])
    elif len(reoccurringOffsets) == 0:
        return None
    else:
        popularOffsets = []
        mostPopularOffset = reoccurringOffsets[0]
    chosenOffset = allOffsets[mostPopularOffset]
    logger.detail(f"{mostPopularOffset}, {chosenOffset}")
    weightedAverageOffset = sum((offset*weight for offset, weight, _ in chosenOffset)) / sum((weight for _, weight, _ in chosenOffset))
    assert abs(weightedAverageOffset) < 120, f"Average offset {weightedAverageOffset} outside of normal range.\nChosen Bucket: {chosenOffset}\nAll offsets: {allOffsets}\nReoccurring offsets: {reoccurringOffsets}\nPopular offsets: {popularOffsets}"
    logger.info(weightedAverageOffset)
    return weightedAverageOffset
    #return sum((offset for offset, _, _ in allOffsets[mostPopularOffset])) / len(allOffsets[mostPopularOffset])
    

def findAverageFileOffset(
    file1: SourceFile,
    file2: SourceFile,
    **kwargs
) -> List[float | Tuple[float, float]]:
    file1Start = file1.infoJson["timestamp"]
    file2Start = file2.infoJson["timestamp"]
    offset = file2Start - file1Start
    file1Path = (
        file1.localVideoFile if file1.localVideoFile is not None else file1.videoFile
    )
    file2Path = (
        file2.localVideoFile if file2.localVideoFile is not None else file2.videoFile
    )
    return findAverageAudioOffset(file1Path, file2Path, offset, **kwargs)

# TODO: First element of return value will be initial offset, all other elements will be a tuple of the start time and time difference for a later offset
# Need to build a way to group offsets by time efficiently
def findAllFileOffsets(file1: SourceFile,
                       file2: SourceFile,
                       **kwargs):
    file1Start = file1.infoJson["timestamp"]
    file2Start = file2.infoJson["timestamp"]
    offset = file2Start - file1Start
    file1Path = file1.localVideoFile if file1.localVideoFile is not None else file1.videoFile
    file2Path = file2.localVideoFile if file2.localVideoFile is not None else file2.videoFile
    return findPopularAudioOffsets(file1Path, file2Path, initialOffset=offset, **kwargs)