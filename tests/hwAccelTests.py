import functools
import os
from pprint import pprint
import sys, shlex


#print = functools.partial(print, end='\n\n')

print(os.getcwd())
print(__file__)

parentDir = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
print(parentDir)
sys.path.insert(0, os.path.abspath(parentDir))
#sys.path.insert(0, os.path.abspath(os.path.join(sys.executable)))
#sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'MultiTwitchRenderer')))

import __main__
from MultiTwitchRenderer import generateTilingCommandMultiSegment
from MTRConfig import getConfig
from ParsedChat import parsePlayersFromGroupMessage
from RenderConfig import RenderConfig
import CommandWorker
from RenderWorker import formatCommand
from SharedUtils import extractInputFiles
from SourceFile import initialize, reloadAndSave, saveFiledata
from SessionWorker import getAllStreamingDaysByStreamer, sessionWorker
import scanned

# %%
#reloadAndSave()


initialize()
print("Initialization complete!")

pprint(getConfig("main.defaultRenderConfig"))

#sessionWorker(
#    renderConfig=RenderConfig(preciseAlign=True)
#)

#CommandWorker.printQueuedJobs()



testCommands = None
#testCommand = generateTilingCommandMultiSegment('ChilledChaos', "2023-11-30", f"/mnt/pool2/media/Twitch Downloads/{outputDirectory}/S1/{outputDirectory} - 2023-11-30 - ChilledChaos.mkv")
#testCommands = generateTilingCommandMultiSegment('ZeRoyalViking', "2023-06-28", 
#testCommands = generateTilingCommandMultiSegment('ChilledChaos', "2023-12-29", 
#testCommands = generateTilingCommandMultiSegment('ChilledChaos', '2024-01-25',
#testCommands = generateTilingCommandMultiSegment('ChilledChaos', '2024-05-04')
testCommands = generateTilingCommandMultiSegment('ChilledChaos', '2024-06-10', renderConfig=RenderConfig(outputCodec = 'hevc_qsv'))

for command in testCommands:
    print("  ".join([shlex.quote(str(e)) for e in command]))
    print("\n")