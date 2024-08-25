from functools import partial
from math import ceil
from random import randrange
from threading import Lock
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
from concurrent.futures import ProcessPoolExecutor, BrokenProcessPool
from multiprocessing.shared_memory import SharedMemory
warnings.filterwarnings('ignore')

import MTRLogging
logger = MTRLogging.getLogger('AudioAlignment')

from SharedUtils import insertSuffix
from SourceFile import SourceFile

sys.path.append(os.path.dirname(sys.executable))

from MTRConfig import getConfig

audioFiles = set()
audioExt = ".m4a"
audioBasepath = os.path.join(getConfig('main.localBasepath'), "extracted-audio")
os.makedirs(audioBasepath, exist_ok=True)


def getAudioPath(videoPath: str):
    # assert any((videoPath.endswith(videoExt) for videoExt in videoExts))
    basepath = getConfig('main.basepath')
    videoExts = getConfig('internal.videoExts')
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
    #if audioPath not in audioFiles:
    if not os.path.isfile(audioPath):
        os.makedirs(os.path.dirname(audioPath), exist_ok=True)
        extractCommand = [
            getConfig('main.ffmpegPath') + "ffmpeg",
            "-i",
            target_file,
            "-vn",
            "-acodec",
            "copy",
            "-y",
            audioPath,
        ]
        subprocess.check_call(extractCommand,
                              stderr=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL,
                              stdin=subprocess.DEVNULL)
        audioFiles.add(audioPath)
    return audioPath


def histogramByBucket(arr, bucketSize = 10):
    ...

MAX_LOAD_DURATION = 7200

DEFAULT_MACRO_WINDOW_SIZE: int = 600
DEFAULT_MICRO_WINDOW_SIZE: int = 10
DEFAULT_BUCKET_SIZE: float | int = 1
DEFAULT_BUCKET_SPILLOVER: int = 1

def loadAudioFile(audioFilePath: str, sr: float | None, start: float, duration: float|None) -> Tuple[np.ndarray, float]:
    try:
        audioData, sampleRate = librosa.load(
            audioFilePath,
            sr=None,
            offset=start,
            duration=duration,
        )
    except Exception as ex:
        logger.warning(f"Got {repr(ex)} when trying to load {audioFilePath}, deleting file and retrying once")
        os.remove(withinAudioFile)
        withinAudioFile = extractAudio(audioFilePath)
        audioData, sampleRate = librosa.load(
            withinAudioFile,
            sr=None,
            offset=start,
            duration=duration,
        )
    return audioData, sampleRate


def _calculateRawAudioOffsets(withinData: np.ndarray,
                             findData: np.ndarray,
                             samplerate: float, 
                             macroWindowSize: int = DEFAULT_MACRO_WINDOW_SIZE,
                             macroStride: int | None = None,
                             microWindowSize: int = DEFAULT_MICRO_WINDOW_SIZE,
                             microStride: float | int | None = None,
                             bucketSize: float | int = DEFAULT_BUCKET_SIZE,
                             bucketSpillover: int = DEFAULT_BUCKET_SPILLOVER):
    startTime = time.time()
    withinLength = withinData.shape[0] / samplerate
    findLength = findData.shape[0] / samplerate
    overlapLength = min(withinLength, findLength)
    offsetsFound: Dict[str, List[Tuple[float, float, float]]] = dict()
    threshold = max(150, 5 * microWindowSize) #500
    #allOffsetsFound: Dict[str, List[Tuple[float, float, float]]] = dict()
    allOffsetsFound: List[tuple] = []
    for macroWindowNum in range(int(ceil((overlapLength - macroWindowSize) / macroStride))):
        macroWindowStart = macroWindowNum * macroStride * samplerate
        macroWindowEnd = ((macroWindowNum * macroStride) + macroWindowSize) * samplerate
        logger.trace(f"Macro start: {macroWindowStart/samplerate}, end: {macroWindowEnd/samplerate}")
        withinSnippet = withinData[macroWindowStart : macroWindowEnd]
        for microWindowNum in range(int(ceil((macroWindowSize - microWindowSize) / microStride))):
            microWindowStart = int(macroWindowStart + (microWindowNum * microStride * samplerate))
            microWindowEnd = int(macroWindowStart + (((microWindowNum * microStride) + microWindowSize) * samplerate))
            logger.trace(f"Micro start: {microWindowStart/samplerate}, end: {microWindowEnd/samplerate}")
            findSnippet = findData[microWindowStart:microWindowEnd]
            c = signal.correlate(withinSnippet, findSnippet, mode='same', method='fft')
            logger.trace(f"Signal correlated, memory tuple: {psutil.virtual_memory()}")
            peak = np.argmax(c)
            logger.trace(f"within shape = {withinSnippet.shape}, find shape = {findSnippet.shape}, c shape = {c.shape}")
            foundOffset = round(((peak + macroWindowStart - microWindowStart) / samplerate) - (microWindowSize / 2), 2)
            offsetStr = str(round(foundOffset / bucketSize) * bucketSize)
            offsetEntry = (foundOffset, c[peak], microWindowStart/samplerate)
            if c[peak] >= threshold:
                logger.trace(f"Found offset {foundOffset}, putting in bucket {offsetStr} (peakHeight={c[peak]}, threshold={threshold}, peakTimeInternal={peak/samplerate})")
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
            logger.trace(f"{key}, {upOneKey}, {downOneKey}")
            if upOneKey in offsetsFound.keys():
                spilledOffsets[key].extend(offsetsFound[upOneKey])
            if downOneKey in offsetsFound.keys():
                spilledOffsets[key].extend(offsetsFound[downOneKey])
    logger.trace(spilledOffsets)
    return spilledOffsets

def findRawAudioOffsetsFromSingleAudioFiles(withinAudiofile: str,
    findAudioFile: str,
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
    #y_within, sr_within = loadAudioFile(withinAudiofile, None, start + (initialOffset if initialOffset > 0 else 0), duration)
    y_within, sr_within = loadAudioFile(withinAudiofile, None, start + max(initialOffset, 0), duration)
    logger.detail(f"First audio loaded in {round(time.time()-startTime, 2)} seconds, memory tuple: {psutil.virtual_memory()}")
    startTime = time.time()
    #y_find, _ = loadAudioFile(findAudioFile, None, start - (initialOffset if initialOffset < 0 else 0), duration)
    y_find, _ = loadAudioFile(findAudioFile, None, start - min(initialOffset, 0), duration)
    logger.detail(f"Second audio loaded in {round(time.time()-startTime, 2)} seconds, memory tuple: {psutil.virtual_memory()}")
    return _calculateRawAudioOffsets(y_within, y_find, sr_within, macroWindowSize, macroStride, microWindowSize, microStride, bucketSize, bucketSpillover)

def findRawAudioOffsetsFromSingleVideoFiles(within_video_file: str,
    find_video_file: str,
    initialOffset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = DEFAULT_MACRO_WINDOW_SIZE,
    macroStride: int | None = None,
    microWindowSize: int = DEFAULT_MICRO_WINDOW_SIZE,
    microStride: float | int | None = None,
    bucketSize: float | int = DEFAULT_BUCKET_SIZE,
    bucketSpillover: int = DEFAULT_BUCKET_SPILLOVER,
    ) -> Dict[str, List[Tuple[float, float, float]]]:
    startTime = time.time()
    if macroWindowSize < 5 * microWindowSize:
        raise ValueError("macroWindowSize should be at least five times microWindowSize for good results")
    if macroWindowSize < 60 * 10:
        raise ValueError("macroWindowSize must be at least 10 minutes")
    if macroStride is None:
        macroStride = macroWindowSize #// 2
    if microStride is None:
        microStride = microWindowSize / 2
    logger.debug(f"Extracting audio from {within_video_file=}")
    withinAudioFile = extractAudio(within_video_file)
    logger.debug(f"Extracting audio from {find_video_file=}")
    findAudioFile = extractAudio(find_video_file)
    logger.info(f"{withinAudioFile}, {findAudioFile}")
    logger.debug(f"Audio extracted in {round(time.time()-startTime, 2)} seconds, memory tuple: {psutil.virtual_memory()}")
    logger.detail(f"Initial offset = {initialOffset}")
    return findRawAudioOffsetsFromSingleAudioFiles(withinAudioFile,
                                                   findAudioFile,
                                                   initialOffset,
                                                   start,
                                                   duration,
                                                   macroWindowSize,
                                                   macroStride,
                                                   microWindowSize,
                                                   microStride,
                                                   bucketSize,
                                                   bucketSpillover)

def findPopularAudioOffsetsFromSingleVideoFiles(
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
    allOffsets = findRawAudioOffsetsFromSingleVideoFiles(within_video_file=within_file,
                                                         find_video_file=find_file,
                                                         initialOffset=initialOffset,
                                                         start=start,
                                                         duration=duration,
                                                         macroWindowSize=macroWindowSize,
                                                         macroStride=macroStride,
                                                         microWindowSize=microWindowSize,
                                                         microStride=microStride,
                                                         bucketSize=bucketSize,
                                                         bucketSpillover=bucketSpillover)
    offsetsByFrequency = sorted(allOffsets.keys(), key=lambda x: -len(allOffsets[x]))
    if len(offsetsByFrequency) == 0:
        return {}
    popularOffsetKeys = [offset for offset in offsetsByFrequency if len(allOffsets[offset]) > popularThreshold]
    logger.debug(f"popularOffsetKeys: {popularOffsetKeys}")
    popularOffsets = {}
    for key in popularOffsetKeys:
        popularOffsets[key] = allOffsets[key]
    return popularOffsets

# TODO: First element of return value will be initial offset, all other elements will be a tuple of the start time and time difference for a later offset
# Need to build a way to group offsets by time efficiently
def findPopularAudioOffsetsFromSingleSourceFiles(file1: SourceFile,
                       file2: SourceFile,
                       **kwargs):
    file1Start = file1.infoJson["timestamp"]
    file2Start = file2.infoJson["timestamp"]
    offset = file2Start - file1Start
    file1Path = file1.localVideoFile if file1.localVideoFile is not None else file1.videoFile
    file2Path = file2.localVideoFile if file2.localVideoFile is not None else file2.videoFile
    return findPopularAudioOffsetsFromSingleVideoFiles(file1Path, file2Path, initialOffset=offset, **kwargs)


def _calculateWeightedAverageAudioOffset(rawOffsets: Dict[str, List[Tuple[float, float, float]]], bucketSize: float) -> float | None:
    if rawOffsets is None or len(rawOffsets) == 0:
        return None
    offsetsByFrequency = sorted(rawOffsets.keys(), key=lambda x: -len(rawOffsets[x]))
    logger.trace(f"offsetsByFrequency {offsetsByFrequency}")
    logger.detail(f"offset lengths: {[(key, len(rawOffsets[key])) for key in offsetsByFrequency]}")
    reoccurringOffsets = [offset for offset in offsetsByFrequency if len(rawOffsets[offset]) > 1]
    logger.debug(f"reoccurringOffsets {reoccurringOffsets}")
    if len(reoccurringOffsets) > 1:
        occurrenceCounts = np.zeros(len(reoccurringOffsets))
        for i in range(len(reoccurringOffsets)):
            occurrenceCounts[i] = len(rawOffsets[reoccurringOffsets[i]])
        avg = np.average(occurrenceCounts)
        stddev = np.std(occurrenceCounts)
        logger.debug(f"avg {avg}, stddev {stddev}")
        popularOffsets = [offset for offset in offsetsByFrequency if len(rawOffsets[offset]) >= avg+stddev]
        if len(popularOffsets) == 0:
            return None
        logger.debug(f"popularOffsets {popularOffsets}")
        mostPopularOffset = popularOffsets[0]
        if len(popularOffsets) > 1:
            secondMostPopularOffset = popularOffsets[1]
            if len(rawOffsets[secondMostPopularOffset]) == len(rawOffsets[mostPopularOffset]):
                if abs(float(mostPopularOffset) - float(secondMostPopularOffset)) > bucketSize:
                    return None
                else:
                    raise NotImplementedError
                    assert len(popularOffsets) == 2 or len(rawOffsets[popularOffsets[2]]) < len(rawOffsets[mostPopularOffset])
                    return None
            totalPopOffsetCount = sum((len(rawOffsets[x]) for x in popularOffsets))
            if len(rawOffsets[mostPopularOffset]) < totalPopOffsetCount * 0.4:
                return None
        #assert len(popularOffsets) <= 1 or len(allOffsets[popularOffsets[1]]) != len(allOffsets[mostPopularOffset])
    elif len(reoccurringOffsets) == 0:
        return None
    else:
        popularOffsets = []
        mostPopularOffset = reoccurringOffsets[0]
    chosenOffset = rawOffsets[mostPopularOffset]
    logger.detail(f"{mostPopularOffset}, {chosenOffset}")
    weightedAverageOffset = sum((offset*weight for offset, weight, _ in chosenOffset)) / sum((weight for _, weight, _ in chosenOffset))
    assert abs(weightedAverageOffset) <= getConfig('internal.audioOffsetCutoff'), f"Average offset {weightedAverageOffset} outside of normal range.\nChosen Bucket: {chosenOffset}\nAll offsets: {rawOffsets}\nReoccurring offsets: {reoccurringOffsets}\nPopular offsets: {popularOffsets}"
    if abs(weightedAverageOffset) > getConfig('internal.audioOffsetCutoff'):
        logger.error(f"Average offset {weightedAverageOffset} outside of normal range!")
        logger.info(f"Chosen Bucket: {chosenOffset}")
        logger.detail(f"Reoccurring offsets: {reoccurringOffsets}")
        logger.info(f"Popular offsets: {popularOffsets}")
        logger.debug(f"All offsets: {rawOffsets}")
        return None
    logger.info(weightedAverageOffset)
    return weightedAverageOffset

def findAverageAudioOffsetFromSingleVideoFiles(
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
) -> None | float:
    allOffsets = findRawAudioOffsetsFromSingleVideoFiles(within_video_file=within_file,
                                      find_video_file=find_file,
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
    averageOffset = _calculateWeightedAverageAudioOffset(allOffsets, bucketSize)
    if averageOffset is None:
        logger.info(f"Unable to align {find_file} to {within_file}")
    return averageOffset
    

def findAverageAudioOffsetFromSingleSourceFiles(
    file1: SourceFile,
    file2: SourceFile,
    **kwargs
) -> None | float:# | Tuple[float, float]:
    file1Start = file1.infoJson["timestamp"]
    file2Start = file2.infoJson["timestamp"]
    offset = file2Start - file1Start
    file1Path = (
        file1.localVideoFile if file1.localVideoFile is not None else file1.videoFile
    )
    file2Path = (
        file2.localVideoFile if file2.localVideoFile is not None else file2.videoFile
    )
    return findAverageAudioOffsetFromSingleVideoFiles(file1Path, file2Path, offset, **kwargs)

processPoolLock = Lock()

sharedMemoryPrefix = "sharedAudioMemory"

def __concurrentOffsetWorker(mainAudioFile:str,
                             mainAudioSamplerate: float,
                             cmpAudioFileInfo: list|tuple,
                             macroWindowSize: int = DEFAULT_MACRO_WINDOW_SIZE,
                             macroStride: int | None = None,
                             microWindowSize: int = DEFAULT_MICRO_WINDOW_SIZE,
                             microStride: float | int | None = None,
                             bucketSize: float | int = DEFAULT_BUCKET_SIZE,
                             bucketSpillover: int = DEFAULT_BUCKET_SPILLOVER) -> float | None:
    cmpAudioFile, offset, start, duration = cmpAudioFileInfo
    
    with open(f"/proc/{os.getpid()}/oom_score_adj", "w") as oom_score_adjust:
        oom_score_adjust.write("1000")  # https://unix.stackexchange.com/a/153586
    
    try:
        sharedMemoryBlock = SharedMemory(sharedMemoryPrefix + mainAudioFile)
        mainSampleCount = sharedMemoryBlock.size / 4
        mainAudioFileData = np.ndarray((mainSampleCount, ), dtype=np.float32, buffer=sharedMemoryBlock.buf)
    except FileNotFoundError:
        logger.info(f"Unable to load audio data in shared memory for {mainAudioFile}, it will be loaded once per worker process")
        time.sleep(randrange(300)) # avoid hammering the filesystem all at once on start
        mainAudioFileData, _sr = loadAudioFile(mainAudioFile, None, start + max(offset, 0), duration)
        assert _sr == mainAudioSamplerate
        del _sr
    
    cmpAudioData, _ = loadAudioFile(cmpAudioFile, mainAudioSamplerate, start - min(offset, 0), duration)
    
    rawOffsets = _calculateRawAudioOffsets(mainAudioFileData,
                                           cmpAudioData,
                                           mainAudioSamplerate,
                                           macroWindowSize,
                                           macroStride,
                                           microWindowSize,
                                           microStride,
                                           bucketSize,
                                           bucketSpillover)
    weightedAverageOffset = _calculateWeightedAverageAudioOffset(rawOffsets, bucketSize)
    return weightedAverageOffset

def findAverageAudioOffsetsFromMultipleSourceFiles(
    mainFile: SourceFile,
    cmpFiles: List[SourceFile],
    cmpFileStartPoints: List[float | int] | None = None,
    cmpFileDurations: List[float | int] | None = None,
    **kwargs
) -> Dict[str, float]:
    allFileOffsets = {}
    if cmpFileDurations is not None and len(cmpFileDurations) != len(cmpFiles):
        raise ValueError(f"List of file durations must be of equal length to the list of files ({len(cmpFileDurations)} != {len(cmpFiles)})")
    if cmpFileStartPoints is not None and len(cmpFileStartPoints) != len(cmpFiles):
        raise ValueError(f"List of file starting points must be of equal length to the list of files ({len(cmpFileDurations)} != {len(cmpFiles)})")
    mainVideoFilePath = mainFile.videoFile if mainFile.localVideoFile is None else mainFile.localVideoFile
    cmpVideoFilePaths = map(lambda x: x.videoFile if x.localVideoFile is None else x.localVideoFile, cmpFiles)
    cmpInitialOffsets = map(lambda x: x.infoJson["timestamp"] - mainFile.infoJson["timestamp"], cmpFiles)
    if cmpFileDurations is None:
        cmpFileDurations = [None] * len(cmpFiles)
    if cmpFileStartPoints is None:
        cmpFileStartPoints = [0] * len(cmpFiles)
    mainAudioFilePath = extractAudio(mainVideoFilePath)
    cmpAudioFilePaths = map(lambda x: extractAudio(x), cmpVideoFilePaths)
    mainAudioData, mainAudioSamplerate = loadAudioFile(mainAudioFilePath, None, 0, None)
    assert mainAudioData.dtype == np.float32
    sharedMemoryBlock = SharedMemory(sharedMemoryPrefix + mainAudioFilePath)
    sharedMainAudioData = np.ndarray(mainAudioData.shape, dtype=np.float32, buffer=sharedMemoryBlock.buf)
    np.copyto(sharedMainAudioData, mainAudioData, 'no')
    
    with processPoolLock:
        processPoolProcessCount = os.cpu_count()
        if processPoolProcessCount is None:
            processPoolProcessCount = 1
        processPoolProcessCount = min(processPoolProcessCount, len(cmpFiles))
        completedAllAlignments = False # completed does not necessarily imply success, just that an attempt at audio alignment has finished
        while not completedAllAlignments and processPoolProcessCount > 1:
            with ProcessPoolExecutor(processPoolProcessCount) as executor:
                try:
                    # TODO: it might be possible to get results one at a time, and potentially save ones that complete before an exception occurs
                    for cmpFile, offset in zip(cmpFiles, executor.map(partial(__concurrentOffsetWorker, mainAudioFilePath, mainAudioSamplerate, **kwargs),
                                                                      zip(cmpAudioFilePaths, cmpInitialOffsets, cmpFileStartPoints, cmpFileDurations))):
                        assert isinstance(cmpFile, SourceFile)
                        if offset is not None:
                            allFileOffsets[cmpFile.videoFile] = offset
                    completedAllAlignments = True
                    break
                except BrokenProcessPool as bpp:
                    logger.debug(bpp, exc_info=1)
                    processPoolProcessCount = int(ceil(processPoolProcessCount / 2))
                    continue
        if not completedAllAlignments:
            assert processPoolProcessCount == 1
            
    
    return allFileOffsets
