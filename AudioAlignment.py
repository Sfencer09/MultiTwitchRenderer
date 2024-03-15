from math import ceil
import time
from typing import Dict, List, Tuple
import librosa
import numpy as np
from scipy import signal
import os
import psutil
import warnings
warnings.filterwarnings('ignore')

from SharedUtils import insertSuffix
from SourceFile import SourceFile

import config
import subprocess

audioFiles = set()
audioExt = ".m4a"
audioBasepath = os.path.join(config.localBasepath, "extracted-audio")
# os.makedirs(audioBasepath, exist_ok=True)


def getAudioPath(videoPath: str):
    # assert any((videoPath.endswith(videoExt) for videoExt in config.videoExts))
    assert videoPath.startswith(config.basepath)
    for videoExt in config.videoExts:
        if videoPath.endswith(videoExt):
            return (
                os.path.join(audioBasepath, videoPath.replace(config.basepath, ""))[
                    : -len(videoExt)
                ]
                + audioExt
            )
    raise ValueError("Must be a video file")


def readExistingAudioFiles():
    for root, _, files in os.walk(audioBasepath):
        for file in [os.path.join(root, file) for file in files]:
            audioFiles.add(file)
    print(audioFiles)


readExistingAudioFiles()


def extractAudio(target_file: str):
    audioPath = getAudioPath(target_file)
    if audioPath not in audioFiles:
        os.makedirs(os.path.dirname(audioPath), exist_ok=True)
        extractCommand = [
            config.ffmpegPath + "ffmpeg",
            "-i",
            target_file,
            "-vn",
            "-acodec",
            "copy",
            audioPath,
        ]
        subprocess.check_call(extractCommand)
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

def findAudioOffsets(within_file: str,
    find_file: str,
    initialOffset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = 3600,
    macroStride: int | None = None,
    microWindowSize: int = 60,
    microStride: float | int | None = 30,
    bucketSize: float | int = 1,
    bucketSpillover: int = 0,
    ):
    startTime = time.time()
    if macroWindowSize < 5 * microWindowSize:
        raise ValueError("macroWindowSize should be at least five times microWindowSize for good results")
    if macroWindowSize < 60 * 10:
        raise ValueError("macroWindowSize must be at least 10 minutes")
    if macroStride is None:
        macroStride = macroWindowSize // 2
    if microStride is None:
        microStride = microWindowSize // 2
    withinAudioFile = extractAudio(within_file)
    findAudioFile = extractAudio(find_file)
    print("Audio extracted, memory tuple:", psutil.virtual_memory())
    print("Initial offset =", initialOffset)
    y_within, sr_within = librosa.load(
        withinAudioFile,
        sr=None,
        offset=start + (initialOffset if initialOffset > 0 else 0),
        duration=duration,
    )
    print("First audio loaded, memory tuple:", psutil.virtual_memory())
    y_find, _ = librosa.load(
        findAudioFile,
        sr=sr_within,
        offset=start - (initialOffset if initialOffset < 0 else 0),
        # duration=window if window is not None else duration,
        duration=duration
    )
    print("Second audio loaded, memory tuple:", psutil.virtual_memory())
    withinLength = y_within.shape[0] / sr_within
    findLength = y_find.shape[0] / sr_within
    overlapLength = min(withinLength, findLength)
    offsetsFound: Dict[str, List[Tuple[float, float]]] = dict()
    threshold = max(100, 5 * microWindowSize) #500
    for macroWindowNum in range(int(ceil((overlapLength - macroWindowSize) / macroStride))):
        macroWindowStart = macroWindowNum * macroStride * sr_within
        macroWindowEnd = ((macroWindowNum * macroStride) + macroWindowSize) * sr_within
        print("Macro start:", macroWindowStart/sr_within, "end:", macroWindowEnd/sr_within)
        withinSnippet = y_within[macroWindowStart : macroWindowEnd]
        for microWindowNum in range(int(ceil((macroWindowSize - microWindowSize) / microStride))):
            microWindowStart = macroWindowStart + (microWindowNum * microStride * sr_within)
            microWindowEnd = macroWindowStart + (((microWindowNum * microStride) + microWindowSize) * sr_within)
            print("Micro start:", microWindowStart/sr_within, "end:", microWindowEnd/sr_within)
            findSnippet = y_find[microWindowStart:microWindowEnd]
            c = signal.correlate(withinSnippet, findSnippet, mode='same', method='fft')
            print("Signal correlated, memory tuple:", psutil.virtual_memory())
            peak = np.argmax(c)
            print("within shape =", withinSnippet.shape, ", find shape =", findSnippet.shape, ", c shape =", c.shape)
            foundOffset = round(((peak + macroWindowStart - microWindowStart) / sr_within) - (microWindowSize / 2), 2)
            if c[peak] >= threshold:
                offsetStr = str(round(foundOffset / bucketSize) * bucketSize)
                print(f"Found offset {foundOffset}, putting in bucket {offsetStr} (peakHeight={c[peak]}, threshold={threshold}, peakTimeInternal={peak/sr_within})")
                if offsetStr in offsetsFound.keys():
                    offsetsFound[offsetStr].append((foundOffset, microWindowStart))
                else:
                    offsetsFound[offsetStr] = [(foundOffset, microWindowStart)]
            else:
                print(f"Found offset {foundOffset} with insufficient peak match (peakHeight={c[peak]}, threshold={threshold}, peakTimeInternal={peak/sr_within})")
    print("Time =", time.time() - startTime, "seconds")
    print(offsetsFound)
    print("\n\n\n")
    if len(offsetsFound) == 0:
        return None
    spilledOffsets: Dict[str, List[float]] = dict()
    for key in offsetsFound.keys():
        spilledOffsets[key] = list(offsetsFound[key])
        keyInt = float(key)
        for offset in range(0, bucketSpillover):
            upOneKey = str(keyInt+(bucketSize*offset))
            downOneKey = str(keyInt-(bucketSize*offset))
            print(key, upOneKey, downOneKey)
            if upOneKey in offsetsFound.keys():
                spilledOffsets[key].extend(offsetsFound[upOneKey])
            if downOneKey in offsetsFound.keys():
                spilledOffsets[key].extend(offsetsFound[downOneKey])
    print(spilledOffsets)
    return spilledOffsets


def findAverageAudioOffset(
    within_file: str,
    find_file: str,
    initialOffset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = 3600,
    macroStride: int | None = None,
    microWindowSize: int = 60,
    microStride: float | int | None = 30,
    bucketSize: float | int = 1,
    bucketSpillover: int = 0,
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
    print(offsetsByFrequency)
    if len(offsetsByFrequency) == 0:
        return None
    popularOffsets = [offset for offset in offsetsByFrequency if len(allOffsets[offset]) > 1]
    print(popularOffsets)
    mostPopularOffset = offsetsByFrequency[0]
    print(mostPopularOffset)
    return sum((offset for offset, _ in allOffsets[mostPopularOffset])) / len(allOffsets[mostPopularOffset])
    

# First element of return value will be initial offset, all other elements will be a tuple of the start time and time difference for a later offset
def findFileOffset(
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
