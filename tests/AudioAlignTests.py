import os
import sys
from typing import Set, TYPE_CHECKING

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# sys.path.insert(0, os.path.abspath(os.path.join(sys.executable)))
#sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "MultiTwitchRenderer")),)
if TYPE_CHECKING:
    from SourceFile import SourceFile


from AudioAlignment import *
import time
import scanned
from MultiTwitchRenderer import generateTilingCommandMultiSegment
from SessionWorker import getAllStreamingDaysByStreamer
from SharedUtils import extractInputFiles
from SourceFile import initialize
from RenderConfig import RenderConfig

initialize()

"""
# file1 = "ChilledChaos/S1/ChilledChaos - 2024-02-15 - IT'S A HARD KNOCK LIFE...FOR US! (The Game of Life 2) ｜ Worms and Intruder After! v2063753759"
file1 = scanned.allFilesByVideoId["v2055212961"] #"ChilledChaos/S1/ChilledChaos - 2024-02-06 - TOWN OF SALEM 2 RETURNS! ｜ Among Us After! v2055212961"
# file2 = "LarryFishburger/S1/LarryFishburger - 2024-02-15 - Showing my Worm to my Friends - !Sponsors !Socials v2063760958"
# file2 = "LarryFishburger/S1/LarryFishburger - 2024-02-06 - Town of Salem 2 w. Friends ：) - !Sponsors !Socials v2055216281"
file2 = scanned.allFilesByVideoId["v2055210338"] #"ZeRoyalViking/S1/ZeRoyalViking - 2024-02-06 - TOWN OF SALEM 2 RETURNS w⧸ Friends (Among Us after!) v2055210338"


print(
    #findAudioOffset(
    #findAverageAudioOffset(
    findFileOffset(
        file1,
        file2,
        duration = 7200,
        macroWindowSize = 30*60,
        macroStride = 30*60,
        microWindowSize = 30
    )
)"""


testStreamer = getConfig('main.monitorStreamers')[0]
allStreamingDays = getAllStreamingDaysByStreamer()
testDay = allStreamingDays[testStreamer][0]
#testDay = "2024-04-02"
def testAudioAlignmentForDate(streamer, day):
    commands = generateTilingCommandMultiSegment(streamer, day)
    if commands is None:
        return None
    mainFiles = set()
    secondaryFiles: Set['SourceFile'] = set()
    for command in commands:
        inputFiles = extractInputFiles(command)
        if len(inputFiles) < 2:
            continue
        mainFiles.add(inputFiles[0])
        secondaryFiles.update(inputFiles[1:])

    assert len(mainFiles) == 1
    print(mainFiles)
    mainFile = scanned.filesBySourceVideoPath[list(mainFiles)[0]]
    offsets = dict()
    startTime = time.time()
    for file in (scanned.filesBySourceVideoPath[f] for f in sorted(secondaryFiles)):
        offset = findAverageAudioOffsetFromSingleSourceFiles(mainFile, file,
            duration = 7200,
            macroWindowSize = 10*60,
            macroStride = 10*60,
            microWindowSize = 10)
        print("Offset: ", offset)
        key = file.videoFile
        offsets[key] = offset
    print(time.time() - startTime, "seconds to run all correlations")
    #print(offsets)
    return offsets

#print(testAudioAlignmentForDate(testStreamer, testDay))
outputs = {}
#for i in range(1, 10):
    #in allStreamingDays[testStreamer]:
    #date = allStreamingDays[testStreamer][i]
    #outputs[date] = testAudioAlignmentForDate(testStreamer, date)
    
#print(outputs)

def testGenerateWithPrecision(streamer, day):
    commands = generateTilingCommandMultiSegment(streamer, day, renderConfig=RenderConfig(preciseAlign = True))
    print(commands)
testGenerateWithPrecision(testStreamer, testDay)