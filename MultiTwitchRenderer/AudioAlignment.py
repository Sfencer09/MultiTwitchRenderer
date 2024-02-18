from typing import Dict, List, Tuple
import librosa
import numpy as np
from scipy import signal
import os
import psutil

import matplotlib.pyplot as plt
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

    return offset

def histogramByBucket(arr, bucketSize = 10):
    ...

def findAverageAudioOffset(
    within_file: str,
    find_file: str,
    offset: float = 0,
    start: float = 0,
    duration: float | None = None,
    macroWindowSize: int = 3600,
    macroStride: int = 1800,
    microWindowSize: int = 60,
    microStride: float = 30,
):
    if macroWindowSize < 5 * microWindowSize:
        raise ValueError("macroWindowSize should be at least five times microWindowSize for good results")
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
        # duration=window if window is not None else duration,
        duration=duration
    )
    print("Second audio loaded, memory tuple:", psutil.virtual_memory())
    withinLength = y_within.shape[0] / sr_within
    findLength = y_find.shape[0] / sr_within
    offsetsFound: Dict[str, List[float]] = dict()
    threshold = 500
    bucketSize: int = 1
    bucketSpillover: int = 1
    for windowNum in range((findLength - microWindowSize) // microStride):
        windowStart = windowNum * microStride * sr_within
        windowEnd = ((windowNum * microStride) + microWindowSize) * sr_within
        findSnippet = y_find[windowStart:windowEnd]
        c = signal.correlate(y_within, findSnippet, mode='full', method='fft')
        print("Signal correlated, memory tuple:", psutil.virtual_memory())
        peak = np.argmax(c)
        if c[peak] >= threshold:
            offsetFound = round((peak - windowStart) / sr_within, 2)
            offsetStr = str(int(offsetFound // bucketSize) * bucketSize)
            print(f"Found offset {offsetFound}, putting in bucket {offsetStr}")
            if offsetStr in offsetsFound.keys():
                offsetsFound[offsetStr].append(offsetFound)
            else:
                offsetsFound[offsetStr] = [offsetFound]

    if len(offsetsFound) == 0:
        return None
    offsetsByFrequency = sorted(offsetFound.keys(), key=lambda x: len(offsetFound[x]))
    print(offsetsByFrequency)
    return np.average(offsetsByFrequency[0])
    

# First element of return value will be initial offset, all other elements will be a tuple of the start time and time difference for a later offset
def findFileOffset(
    file1: SourceFile,
    file2: SourceFile,
    duration: float | None = __DEFAULT_DURATION,
    window: float | None = __DEFAULT_WINDOW,
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
    return findAudioOffset(file1Path, file2Path, offset, duration, window)
