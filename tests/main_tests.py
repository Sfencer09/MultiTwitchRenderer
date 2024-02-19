# %%
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
#sys.path.insert(0, os.path.abspath(os.path.join(sys.executable)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'MultiTwitchRenderer')))

from MultiTwitchRenderer.MultiTwitchRenderer import generateTilingCommandMultiSegment
from MultiTwitchRenderer.ParsedChat import parsePlayersFromGroupMessage
from MultiTwitchRenderer.RenderConfig import RenderConfig
from MultiTwitchRenderer.RenderWorker import formatCommand
from MultiTwitchRenderer.SharedUtils import extractInputFiles
from MultiTwitchRenderer.SourceFile import initialize

# %%
#reloadAndSave()


initialize()
#loadFiledata(DEFAULT_DATA_FILEPATH+'.bak')
#scanFiles(log=True)
print("Initialization complete!")

#testCommand = generateTilingCommandMultiSegment('ChilledChaos', "2023-11-30", f"/mnt/pool2/media/Twitch Downloads/{outputDirectory}/S1/{outputDirectory} - 2023-11-30 - ChilledChaos.mkv")
#testCommands = generateTilingCommandMultiSegment('ZeRoyalViking', "2023-06-28", 
#testCommands = generateTilingCommandMultiSegment('ChilledChaos', "2023-12-29", 
testCommands = generateTilingCommandMultiSegment('ChilledChaos', '2024-01-25',
                                                 RenderConfig(logLevel=3,
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
                                                 ))



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
#pprint(allFilesByVideoId['v2028655388'].parsedChat.groups)
#print(allStreamersWithVideos)
parsePlayersFromGroupMessage("Chilled is playing with AstarriApple, BryceMcQuaid, CheesyBlueNips, DooleyNotedGaming (Jeremy), HeckMuffins, KaraCorvus, KYR_SP33DY, LarryFishburger, VikramAFC, X33N, and ZeRoyalViking!!  ")


# %%
def printAbove(s:str, linesAbove:int, *, printFunc=print):
    #goUp = '\x1b[A' * linesAbove
    goUp = '\033[1A' * linesAbove
    goDown = '\n' * linesAbove
    printFunc(f"{goUp}\r{s}{goDown}", end='')
    
print("test123\nTEST321\nThis is a test\nTesting", end='')
printAbove("Overwritten!!!", 2)

