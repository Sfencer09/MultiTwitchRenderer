# %%
import functools
import os
from pprint import pprint
import sys

print(os.getcwd())
print(__file__)

parentDir = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
print(parentDir)
sys.path.insert(0, os.path.abspath(parentDir))
#sys.path.insert(0, os.path.abspath(os.path.join(sys.executable)))
#sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'MultiTwitchRenderer')))

import __main__
from MultiTwitchRenderer import generateTilingCommandMultiSegment
from config import *
from ParsedChat import parsePlayersFromGroupMessage
from RenderConfig import RenderConfig
from RenderWorker import formatCommand
from SharedUtils import extractInputFiles
from SourceFile import initialize, reloadAndSave, saveFiledata
from SessionWorker import getAllStreamingDaysByStreamer, sessionWorker
import scanned

# %%
#reloadAndSave()


initialize()
#loadFiledata(DEFAULT_DATA_FILEPATH+'.bak')
#scanFiles(log=True)
print("Initialization complete!")
print(len(scanned.allFilesByVideoId))

# %%

sessionWorker()

# %%

#testCommand = generateTilingCommandMultiSegment('ChilledChaos', "2023-11-30", f"/mnt/pool2/media/Twitch Downloads/{outputDirectory}/S1/{outputDirectory} - 2023-11-30 - ChilledChaos.mkv")
#testCommands = generateTilingCommandMultiSegment('ZeRoyalViking', "2023-06-28", 
#testCommands = generateTilingCommandMultiSegment('ChilledChaos', "2023-12-29", 
#testCommands = generateTilingCommandMultiSegment('ChilledChaos', '2024-01-25',
testStreamer = mainStreamers[0]
testCommands = None
dateIndex = 0
allStreamingDays = getAllStreamingDaysByStreamer()
while testCommands is None:
    testDay = allStreamingDays[testStreamer][dateIndex]
    testCommands = generateTilingCommandMultiSegment(testStreamer, testDay #,
                                                 #RenderConfig(#logLevel=3,
                                                 #startTimeMode='allOverlapStart',
                                                 #endTimeMode='allOverlapEnd',
                                                 #useHardwareAcceleration=HW_DECODE,#|HW_INPUT_SCALE,#|HW_ENCODE,#|HW_OUTPUT_SCALE
                                                 #sessionTrimLookback=0,#3, #TODO: convert from number of segments to number of seconds. Same for lookahead
                                                 #minimumTimeInVideo=1200,
                                                 ##minGapSize=1800,
                                                 #maxHwaccelFiles=20,
                                                 #useChat=False,
                                                 #drawLabels=True,
                                                  #sessionTrimLookback=1, 
                                                  #sessionTrimLookahead=-1,
                                                  #outputCodec='libx264',
                                                  #encodingSpeedPreset='medium',
                                                  #useHardwareAcceleration=0, #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale input, bit 3(4)=scale output, bit 4(8)=encode
                                                  #minimumTimeInVideo=900,
                                                  #cutMode='chunked',
                                                  #useChat=True,
                                                 )#)
    dateIndex += 1

print([extractInputFiles(testCommand) for testCommand in testCommands])
print("\n\n")
for testCommand in testCommands:
    if 'ffmpeg' in testCommand[0]:
        testCommand.insert(-1, '-y')
        testCommand.insert(-1, '-stats_period')
        testCommand.insert(-1, '30')
        #testCommand.insert(-1, )
#print(testCommands)
#testCommandString = formatCommand(testCommand)
testCommandStrings = [formatCommand(testCommand) for testCommand in testCommands]
#print(testCommandStrings)
def writeCommandStrings(commandList, testNum=None):
    if testNum is None:
        for i in range(2,1000):
            path = f"/mnt/pool2/media/ffmpeg test{str(i)}.txt"
            if not os.path.isfile(path):
                testNum = i
    path = f"/mnt/pool2/media/ffmpeg test{str(testNum)}.txt"
    print(path)
    with open(path, 'w') as file:
        file.write('\n'.join(commandList))
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
        file.write(' && \\\n'.join(commandList))
        file.write(' && \\\necho "Render complete!!"')

#writeCommandStrings(testCommandStrings, 10)
#writeCommandScript(testCommandStrings, 11)

# %%
#targetGroups = scanned.allFilesByVideoId['v2082233820'].parsedChat.groups
targetGroups = scanned.allFilesByVideoId['v2076440501'].parsedChat.groups
pprint([targetGroups[i] for i in range(len(targetGroups)) if i == 0 or set(targetGroups[i]) != set(targetGroups[i-1])])
#print(allStreamersWithVideos)
#parsePlayersFromGroupMessage("Chilled is playing with AstarriApple, BryceMcQuaid, CheesyBlueNips, DooleyNotedGaming (Jeremy), HeckMuffins, KaraCorvus, KYR_SP33DY, LarryFishburger, VikramAFC, X33N, and ZeRoyalViking!!  ")
print(parsePlayersFromGroupMessage("Chilled is playing with APlatypuss(Soon), AriBunnie, AstarriApple(Soon), HeckMuffins, JonSandman, KaraCorvus, OzzaWorld(Soon), Reenyy, TayderTot, X33N, and VikramAFC!!"))

# %%
print(scanned.allFilesByVideoId['v2082233820'])

testCommands = generateTilingCommandMultiSegment(testStreamer, "2024-03-05")

testInputFiles = [extractInputFiles(testCommand) for testCommand in testCommands]
uniqueFiles = sorted(set(functools.reduce(list.__add__, testInputFiles, [])))
print(testInputFiles)
print(uniqueFiles)
print("\n\n")

saveFiledata(DEFAULT_DATA_FILEPATH)


# %%
def printAbove(s:str, linesAbove:int, *, printFunc=print):
    #goUp = '\x1b[A' * linesAbove
    goUp = '\033[1A' * linesAbove
    goDown = '\n' * linesAbove
    printFunc(f"{goUp}\r{s}{goDown}", end='')
    
#print("test1\nTEST2\nThis is a test\nTesting", end='')
#printAbove("Overwritten!!!", 2)


# %%

#import AudioAlignTests