
from functools import partial
import queue
import shutil
import threading
import time 
import os

from SharedUtils import extractInputFiles



import config
import scanned

from RenderWorker import renderQueue, renderQueueLock
from RenderTask import RenderTask, getRenderStatus, setRenderStatus, incrFileRefCount, DEFAULT_PRIORITY

if config.COPY_FILES:
    activeCopyTask: RenderTask = None
    copyThread: threading.Thread = None
    copyQueue = queue.PriorityQueue()
    copyQueueLock = threading.RLock()

def copyWorker(copyLog=partial(print, flush=True)):
    #copyLog = copyText.addLine
    queueEmpty = False
    try: # This try catch is here so I don't have to finish fixing whatever is f*cked up with my PyInstaller setup
        from MultiTwitchRenderer.MultiTwitchRenderer import generateTilingCommandMultiSegment
        #This will work if it is in the PyInstaller package
    except:
        # But if it's not, and we're just running it in VSCode, then this import will take over instead.
        from MultiTwitchRenderer import generateTilingCommandMultiSegment
    while True:
        if copyQueue.empty():
            if not queueEmpty:
                print("Copy queue empty, sleeping")
                queueEmpty = True
            time.sleep(10)
            continue
            # return
        queueEmpty = False
        copyQueueLock.acquire()  # block if user is editing queue
        priority, task = copyQueue.get(block=False)
        copyQueueLock.release()
        assert getRenderStatus(
            task.mainStreamer, task.fileDate) == 'COPY_QUEUE'
        global activeCopyTask
        activeCopyTask = task
        setRenderStatus(task.mainStreamer, task.fileDate, 'COPYING')
        commandArray = generateTilingCommandMultiSegment(task.mainStreamer,
                                                         task.fileDate,
                                                         task.renderConfig,
                                                         task.outputPath)
        # outputPath = [command for command in commandArray if 'ffmpeg' in command[0]][-1][-1]
        renderCommands = [
            command for command in commandArray if 'ffmpeg' in command[0]]
        allInputFiles = [filepath for command in renderCommands for filepath in extractInputFiles(
            command) if type(filepath) == str and 'anullsrc' not in filepath]
        # print(commandArray)
        allOutputFiles = set([command[-1] for command in renderCommands])
        overallOutputFile = renderCommands[-1][-1]
        sourceFiles = [scanned.filesBySourceVideoPath[filepath]
                       for filepath in allInputFiles if filepath not in allOutputFiles]
        # self.intermediateFiles = set([command[-1] for command in commandArray[:-1] if 'ffmpeg' in command[0]])
        # renderCommand = list(task.commandArray)
        for file in sourceFiles:
            remotePath = file.videoFile
            localPath = remotePath.replace(config.basepath, config.localBasepath)
            if not os.path.isfile(localPath):
                # time.sleep(5)
                copyLog(f"Copying file {remotePath} to local storage")
                # copy to temp file to avoid tripping the if condition with incomplete transfers
                shutil.copyfile(remotePath, localPath+'.temp')
                copyLog('File copy complete, moving to location')
                shutil.move(localPath+'.temp', localPath)
                copyLog('Move complete')
            else:
                copyLog('Local file already exists')
            incrFileRefCount(localPath)
            # copy file and update SourceFile object
            file.localVideoPath = localPath
            # add copied file to filesBySourceVideoPath
            scanned.filesBySourceVideoPath[localPath] = file
            # replace file path in renderCommand
            for command in task.commandArray:
                command[command.index(remotePath)] = localPath
        copyLog(
            f'Finished source file copies for render to {overallOutputFile}')
        # item = QueueItem(streamer, day, renderConfig, outPath)
        copyQueue.task_done()
        queueItem = (DEFAULT_PRIORITY, RenderTask(task.mainStreamer,
                     task.fileDate, task.renderConfig, task.outputPath))
        renderQueueLock.acquire()  # block if user is editing queue
        renderQueue.put(queueItem)
        renderQueueLock.release()
        setRenderStatus(task.mainStreamer, task.fileDate, 'RENDER_QUEUE')

