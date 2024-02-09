
from functools import partial
import os
from typing import List
from thefuzz import process as fuzzproc
import time as ttime
from SharedUtils import getVideoOutputPath

import config
from RenderWorker import endRendersAndExit, renderThread, activeRenderTask, activeRenderTaskSubindex, renderQueue, renderQueueLock
if config.COPY_FILES:
    from CopyWorker import activeCopyTask, copyQueue, copyQueueLock
from SourceFile import allStreamersWithVideos
from MultiTwitchRenderer import calcGameCounts
from RenderConfig import RenderConfig
from RenderTask import DEFAULT_PRIORITY, MANUAL_PRIORITY, MAXIMUM_PRIORITY, RenderTask, clearErroredStatuses, deleteRenderStatus, getRenderStatus, getRendersWithStatus, setRenderStatus
from SessionWorker import getAllStreamingDaysByStreamer

class Command:
    def __init__(self, targetFunc, description):
        self.targetFunc = targetFunc
        self.description = description


commandArray:List[Command] = []

commandArray.append(Command(endRendersAndExit, 'Exit program'))


def startRenderThread():
    print("Starting render thread")
    if renderThread is not None and not renderThread.is_alive():
        renderThread.start()
    index = None
    for i in range(len(commandArray)):
        if commandArray[i].targetFunc == startRenderThread:
            index = i
            break
    assert index is not None
    del commandArray[index]


commandArray.append(Command(startRenderThread, 'Start render thread'))


def printActiveJobs():
    print(f"Active render job:",
          "None" if activeRenderTask is None else f"{str(activeRenderTask)}, subindex {str(activeRenderTaskSubindex)}\n{activeRenderTask.__repr__()}")
    if config.COPY_FILES:
        print(f"Active copy job:",
              "None" if activeCopyTask is None else f"{str(activeCopyTask)}")


commandArray.append(Command(printActiveJobs, 'Print active jobs'))


def printQueuedJobs():
    if len(renderQueue.queue) == 0:
        print("Render queue: empty")
    else:
        for queueItem in sorted(renderQueue.queue):
            print(queueItem)
    if config.COPY_FILES:
        if len(copyQueue.queue) == 0:
            print("Copy queue: empty")
        else:
            for queueItem in sorted(copyQueue.queue):
                print(queueItem)


commandArray.append(Command(printQueuedJobs, 'Print queued jobs'))


def printJobsWithStatus(status):
    #renderStatusLock.acquire()
    #selectedRenders = [key.split(
    #    '|') for key in renderStatuses.keys() if renderStatuses[key] == status]
    #renderStatusLock.release()
    selectedRenders = getRendersWithStatus(status)
    streamersWithSelected = sorted(
        set([render[0] for render in selectedRenders]))
    # print(streamersWithSelected)
    selectedStreamer = None
    if len(streamersWithSelected) > 1:
        print("Select streamer (blank for all):")
        for i in range(len(streamersWithSelected)):
            streamer = streamersWithSelected[i]
            count = len(
                [render for render in selectedRenders if render[0] == streamer])
            print(f"{i+1}: {streamer} ({count} renders)")
        userInput = input(" >> ")
        try:
            selectedStreamer = streamersWithSelected[int(userInput)-1]
        except:
            selectedStreamer = None
    formattedStatus = status[0].upper()+status[1:].lower()
    print(f"{formattedStatus} renders:")
    print(f"Streamer                  | File date")
    for streamer, date in sorted(selectedRenders):
        if selectedStreamer is None or streamer == selectedStreamer:
            print(f"{streamer:25} | {date}")


commandArray.append(
    Command(partial(printJobsWithStatus, 'FINISHED'), 'Print completed jobs'))
commandArray.append(
    Command(partial(printJobsWithStatus, 'ERRORED'), 'Print errored jobs'))


def clearErroredJobs():
    #selectedRenders = [key.split('|') for key in renderStatuses.keys(
    #) if renderStatuses[key] == 'ERRORED']
    selectedRenders = getRendersWithStatus('ERRORED')
    streamersWithSelected = sorted(
        set([render[0] for render in selectedRenders]))
    # print(streamersWithSelected)
    selectedStreamer = None
    if len(streamersWithSelected) > 1:
        print("Select streamer (blank for all, 'q' to cancel):")
        for i in range(len(streamersWithSelected)):
            streamer = streamersWithSelected[i]
            count = len(
                [render for render in selectedRenders if render[0] == streamer])
            print(f"{i+1}: {streamer} ({count} errored jobs)")
        userInput = input(" >> ")
        if len(userInput) > 0:
            if userInput.lower() in quitOptions:
                return
            try:
                selectedStreamer = streamersWithSelected[int(userInput)-1]
            except:
                selectedStreamer = None
    for streamer, date in selectedRenders:
        if selectedStreamer is None or streamer == selectedStreamer:
            print(f"Clearing error status for {streamer} {date}")
            #deleteRenderStatus(streamer, date, lock=False)
            clearErroredStatuses(streamer)
    


commandArray.append(Command(clearErroredJobs, 'Clean up errored jobs'))

quitOptions = ('quit', 'exit', 'q')

# ... = done
# None = cancel/quit


def readStreamer(allStreamersList=None, inputText="Enter streamer name, or 'list' to list valid names. 'q' to exit/cancel: "):
    # print(allStreamersWithVideos)
    if allStreamersList is None:
        allStreamersList = allStreamersWithVideos
    print("Available streamers:", allStreamersList)
    while True:
        print(inputText)
        userInput = input(" >> ")
        if userInput == '':
            return ...
        elif userInput.lower() in quitOptions:
            return None
        elif userInput.lower() == 'list':
            for streamer in allStreamersList:
                print(streamer)
            continue
        for streamer in allStreamersList:
            if streamer.lower() == userInput.lower():
                return streamer
        closestMatch, ratio = fuzzproc.extractOne(userInput, allStreamersList)
        if ratio < 50:
            print("Could not parse streamer name, please try again")
            #if requireVideos:
            print("(If the streamer name is valid, they may not have any known videos)")
            continue
        isMatch = input(
            f"Streamer '{userInput}' not found, did you mean '{closestMatch}'? ({str(ratio)}% match) (y/n) ")
        if isMatch.lower().startswith('y'):
            return closestMatch


def readExcludeStreamers():  # TODO: rename to be more generic
    print("Selecting streamers to exclude, or empty input when done entering")
    streamerExclusions = {}
    while True:
        parsedStreamer = readStreamer(
            inputText="Enter streamer name, or 'list' to list valid names. 'q' to exit/cancel. Leave empty if done: ")
        if parsedStreamer is None:
            return None
        elif parsedStreamer == ...:
            if len(streamerExclusions) == 0:
                print("No streamers entered, cancelling")
                return None
            else:
                break
        allGames = sorted(
            ((game, count) for game, count in calcGameCounts().items()), key=lambda x: -x[1])
        print(f"Streamer {parsedStreamer} selected")
        excludedGames = []

        def readExcludeGame():
            gamesPage = 0
            gamesPageSize = 20
            while True:
                startIndex = gamesPage*gamesPageSize
                endIndex = (gamesPage+1)*gamesPageSize
                pageGames = allGames[startIndex:endIndex]
                hasPrevPage = gamesPage > 0
                hasNextPage = endIndex < len(allGames)
                if hasPrevPage:
                    print("P) Previous page")
                for i in range(len(pageGames)):
                    print(f"{i+1}) {pageGames[i][0]}")
                if hasNextPage:
                    print("N) Next page")
                userInput = input(" >> ")
                if userInput.lower() in quitOptions:
                    return None
                elif userInput.lower() == 'p':
                    if hasPrevPage:
                        gamesPage -= 1
                        continue
                    else:
                        print("No previous page")
                elif userInput.lower() == 'n':
                    if hasNextPage:
                        gamesPage += 1
                        continue
                    else:
                        print("No next page")
                elif userInput == '':
                    return ...
                elif userInput.isdigit():
                    index = int(userInput)-1
                    if not 0 < index <= len(pageGames):
                        print(
                            f"Entered number outside of valid range (1-{len(pageGames)})")
                        continue
                    return pageGames[index][0]
                else:
                    for game, _ in allGames:
                        if game.lower() == userInput.lower():
                            return excludeGame
        while True:
            if len(excludedGames) > 0:
                print(f"Excluded games so far: {str(excludedGames)}")
                print(
                    f"Enter game number or manually enter game name. Leave blank to end game selection or 'q' to abort:")
            else:
                print(
                    f"Enter game number or manually enter game name. Leave blank to select all games or 'q' to abort:")
            excludeGame = readExcludeGame()
            if excludeGame is None:
                return None
            elif excludeGame == ...:
                break
            else:
                excludedGames.append(excludeGame)
        if len(excludedGames) == 0:
            streamerExclusions[parsedStreamer] = None
        else:
            streamerExclusions[parsedStreamer] = excludedGames
    return streamerExclusions


renderConfigSchemaManualHandles = {'excludeStreamers': readExcludeStreamers,
                                   'includeStreamers': readExcludeStreamers}


def readRenderConfig(initialRenderConfig=None):
    renderConfig = initialRenderConfig
    if renderConfig is None:
        renderConfig = RenderConfig()
    print(renderConfig.__dict__)
    print(len(renderConfig.__dict__.keys()))
    while True:  # manually break out
        configDict = renderConfig.__dict__
        print("Current render settings:")
        sortedKeys = sorted(configDict.keys())
        for i in range(len(sortedKeys)):
            print(f"{i+1}) {sortedKeys[i]} = {str(configDict[sortedKeys[i]])}")
        print("F) Finish and queue render")
        userInput = input(" >> ")
        if userInput in quitOptions:
            return None
        elif userInput.lower() == 'f':
            return renderConfig
        try:
            selectedKey = sortedKeys[int(userInput)-1]
        except:
            print(f"Invalid selection: '{userInput}'")
            continue
        if selectedKey in renderConfigSchemaManualHandles.keys():
            newValue = renderConfigSchemaManualHandles[selectedKey]()
        else:
            print(f"New value for {selectedKey}: ")
            newValue = input(" >> ")
        configDict[selectedKey] = newValue


def inputManualJob(initialRenderConfig=None):
    allStreamerDays = getAllStreamingDaysByStreamer()
    mainStreamer = readStreamer(allStreamerDays.keys())
    if mainStreamer is None or mainStreamer == ...:
        return
    fileDate = None
    streamerDays = allStreamerDays[mainStreamer]
    if len(streamerDays) == 0:
        print("Selected streamer has no streams!")
        return
    pageNum = 0
    pageSize = 30
    pageWidth = 3
    while fileDate is None:
        print("Enter file date to render:")
        optionRows = []
        hasPrevPage = pageNum > 0
        if hasPrevPage:
            print("P) Previous page")
        startIndex = pageNum*pageSize
        endIndex = (pageNum+1)*pageSize
        dates = streamerDays[startIndex:endIndex]
        for dayIndex in range(len(dates)):
            print(f"{dayIndex+1}) {dates[dayIndex]}    ", end='')
            if dayIndex % pageWidth == pageWidth-1 or dayIndex == len(dates)-1:
                print()
        hasNextPage = endIndex < len(streamerDays)
        if hasNextPage:
            print("N) Next page")
        userInput = input(" >> ")
        if userInput.lower() == 'p':
            if hasPrevPage:
                pageNum -= 1
                continue
            else:
                print("No previous page!")
        elif userInput.lower() == 'n':
            if hasNextPage:
                pageNum += 1
                continue
            else:
                print("No next page!")
        elif userInput.lower() in quitOptions:
            return
        try:
            fileDate = dates[int(userInput)-1]
        except:
            print("Invalid input!")
            ttime.sleep(2)
            fileDate = None
    currentStatus = getRenderStatus(mainStreamer, fileDate)
    print(f"Got {mainStreamer} {fileDate}, current status {currentStatus}")

    outputPath = input("Enter output path (Leave blank for default):\n")
    if outputPath == '':
        outputPath = getVideoOutputPath(mainStreamer, fileDate)

    if currentStatus == 'RENDER_QUEUE':
        raise Exception("Editing queued renders not supported yet")
    renderConfig = readRenderConfig()
    if renderConfig is None:
        return None
    item = RenderTask(mainStreamer, fileDate, renderConfig, outputPath)
    print(f"Adding render for streamer {mainStreamer} from {fileDate}")
    setRenderStatus(mainStreamer, fileDate,
                    'COPY_QUEUE' if config.COPY_FILES else 'RENDER_QUEUE')
    (copyQueue if config.COPY_FILES else renderQueue).put((MANUAL_PRIORITY, item))


commandArray.append(Command(inputManualJob, 'Add new manual job'))


def editQueueItem(queueEntry):
    priority, item = queueEntry
    mainStreamer = item.mainStreamer
    fileDate = item.fileDate
    renderConfig = item.renderConfig
    outputPath = item.outputPath
    while True:
        print("Current values:")
        print(f"Render config: {str(renderConfig)}")
        print(f"Priority: {priority}")
        print(f"Output path: {outputPath}")
        print("Select option:")
        print("R) Render configuration\nP) Priority\nO) Output path\nD) Delete item from queue\nF) Finish editing and re-add to queue")
        userInput = input(" >> ")
        if userInput.lower() in quitOptions:
            return None
        elif userInput.lower() == 'r':
            renderConfig = readRenderConfig(renderConfig)
        elif userInput.lower() == 'p':
            valueInput = input(
                f"Enter new priority (0-{MAXIMUM_PRIORITY}, default is {DEFAULT_PRIORITY}):  ")
            try:
                value = int(valueInput)
                if not 0 <= value <= MAXIMUM_PRIORITY:
                    print("Value outside of valid range!")
                    continue
                priority = value
            except:
                print(
                    f"Unable to parse priority '{valueInput}'! Must be a positive integer")
                continue
        elif userInput.lower() == 'o':
            print(
                f"Enter new output path (relative to {config.basepath}), blank to cancel:")
            valueInput = input(config.basepath)
            if len(valueInput) == 0:
                continue
            elif valueInput.lower() in quitOptions:
                return None
            elif not any((valueInput.endswith(ext) for ext in config.videoExts)):
                print(
                    f"Output path must be that of a video file - must end with one of: {', '.join(config.videoExts)}")
                continue
            else:
                outputPath = os.path.join(config.basepath, valueInput)
        elif userInput.lower() == 'f':
            break
        elif userInput.lower() == 'd':
            deleteRenderStatus(mainStreamer, fileDate)
            return ...
        else:
            print(f"Invalid option: '{userInput}'")
    newItem = RenderTask(mainStreamer, fileDate, renderConfig, outputPath)
    return (priority, newItem)


def editQueue():
    selectedQueue = None
    selectedQueueLock = None
    if config.COPY_FILES:
        print("Select queue:\nR) Render queue\nC) Copy queue")
        while selectedQueue is None:
            userInput = input(" >> ")
            if userInput.lower().startswith('r'):
                selectedQueue = renderQueue
                selectedQueueLock = renderQueueLock
            elif userInput.lower().startswith('c'):
                selectedQueue = copyQueue
                selectedQueueLock = copyQueueLock
            elif userInput.lower() in quitOptions:
                return
            else:
                print(f"Unrecognized input ('q' to quit): '{userInput}'")
    else:
        selectedQueue = renderQueue
        selectedQueueLock = renderQueueLock
    selectedQueueLock.acquire()
    items = []
    while not selectedQueue.empty():
        items.append(selectedQueue.get())
    while True:
        if len(items) == 0:
            print("Queue is empty!")
            selectedQueueLock.release()
            return
        print("Select queue item to edit: ")
        for i in range(len(items)):
            priority, queueItem = items[i]
            mainStreamer = queueItem.mainStreamer
            fileDate = queueItem.fileDate
            print(f"{i+1}) {mainStreamer} {fileDate} (priority: {priority})")
        userInput = input(" >> ")
        if len(userInput) == 0 or userInput.lower() in quitOptions:
            break
        try:
            index = int(userInput)-1
            selectedItem = items[index]
            modifiedItem = editQueueItem(selectedItem)
            if modifiedItem is None:
                break
            elif modifiedItem == ...:
                del items[index]
            else:
                items[index] = modifiedItem
                items.sort()
        except:
            print(f"Invalid input: '{userInput}'")
            continue
    for item in items:  # push modified items back into queue with their new priorities
        selectedQueue.put(item)
    selectedQueueLock.release()


commandArray.append(Command(editQueue, 'Edit queue(s)'))


def commandWorker():
    while True:
        for _ in range(5):
            print()
        for i in range(len(commandArray)):
            command = commandArray[i]
            print(f"{str(i)}. {command.description}")
        # print("\n\n\n\n\n\n0. Exit program\n1. Print active jobs\n2. Print queued jobs\n3. Manually add job\n4. Modify/rerun job\n")
        userInput = input(" >> ")
        if __debug__ and userInput.lower() in quitOptions:
            return
        if not userInput.isdigit():
            print(f"Invalid input: '{userInput}'")
            print("Please try again")
            continue
        optionNum = int(userInput)
        if optionNum < 0 or optionNum > len(commandArray):
            print(f"Invalid option number: {userInput}")
            print("Please try again")
        try:
            commandArray[optionNum].targetFunc()
        except KeyboardInterrupt as ki:
            print(
                "Detected keyboard interrupt, returning to main menu. Press Ctrl-C again to exit program")
        # raise Exception("Not implemented yet")
