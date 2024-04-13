from functools import partial
import shutil
import time
import signal
import queue
import threading
import gc
import subprocess
import sys
import os
from shlex import quote
from typing import Any, Tuple

from MTRConfig import getConfig

from MTRLogging import getLogger
logger = getLogger('RenderWorker')


from RenderTask import RenderTask, getRenderStatus
from SharedUtils import insertSuffix
from SourceFile import getVideoInfo
from RenderTask import setRenderStatus, getRenderStatus, decrFileRefCount
from MultiTwitchRenderer import generateTilingCommandMultiSegment

renderThread:threading.Thread = None
activeRenderTask:RenderTask = None
activeRenderTaskSubindex:int = None
activeRenderSubprocess:subprocess.Popen = None

renderQueue: queue.PriorityQueue[Tuple[int, RenderTask]] = queue.PriorityQueue()
renderQueueLock = threading.Lock()

def formatCommand(command):
    return ' '.join((quote(str(x)) for x in command))

def startRenderThread():
    if not renderThreadStarted():
        renderThread.start()
        return True
    return False

def renderThreadStarted():
    return renderThread is not None and renderThread.is_alive()

def getActiveRenderTaskInfo() -> Tuple[RenderTask, int, subprocess.Popen]:
    return (activeRenderTask, activeRenderTaskSubindex, activeRenderSubprocess)

def renderWorker(stats_period=30,  # 30 seconds between encoding stats printing
                 overwrite_intermediate=getConfig('main.overwriteIntermediateFiles'),
                 overwrite_output=getConfig('main.overwriteOutputFiles'),
                 renderLog=None):
    #renderLog = renderText.addLine
    queueEmpty = False
    logFolder = getConfig('main.logFolder')
    localBasepath = getConfig('main.localBasepath')
    while True:
        # sessionText, copyText, renderText = bufferedTexts
        if renderQueue.empty():
            if not queueEmpty:
                logger.detail("Render queue empty, sleeping")
                queueEmpty = True
            time.sleep(10)
            continue
        queueEmpty = False
        renderQueueLock.acquire()  # block if user is editing queue
        priority, task = renderQueue.get(block=False)
        renderQueueLock.release()

        assert getRenderStatus(
            task.mainStreamer, task.fileDate) == 'RENDER_QUEUE'
        global activeRenderTask
        global activeRenderTaskSubindex
        activeRenderTask = task
        taskCommands = generateTilingCommandMultiSegment(task.mainStreamer,
                                                         task.fileDate,
                                                         task.renderConfig,
                                                         task.outputPath)
        renderCommands = [
            command for command in taskCommands if command[0].endswith('ffmpeg')]
        if not overwrite_output:
            outpath = renderCommands[-1][-1]
            count = 1
            suffix = ""
            while os.path.isfile(insertSuffix(outpath, suffix)):
                suffix = f" ({count})"
                count += 1
            renderCommands[-1][-1] = insertSuffix(outpath, suffix)
        finalOutpath = renderCommands[-1][-1]
        # shutil.move(tempOutpath, insertSuffix(outpath, suffix))
        # print(renderCommands)
        # pathSplitIndex = outpath.rindex('.')
        # tempOutpath = outpath[:pathSplitIndex]+'.temp'+outpath[pathSplitIndex:]
        # tempOutpath = insertSuffix(outpath, '.temp')
        # print(outpath, tempOutpath)
        # renderCommands[-1][-1] = tempOutpath # output to temp file, so final filename will always be a complete file
        for i in range(len(renderCommands)):
            renderCommands[i].insert(-1, "-stats_period")
            renderCommands[i].insert(-1, str(stats_period))
            # overwrite (temp) file if it exists
            renderCommands[i].insert(-1, '-y')
        setRenderStatus(task.mainStreamer, task.fileDate, 'RENDERING')
        hasError = False
        gc.collect()
        tempFiles = []
        for i in range(len(taskCommands)):
            activeRenderTaskSubindex = i
            # TODO: add preemptive scheduling
            with open(os.path.join(logFolder, f"{task.mainStreamer}_{task.fileDate}{'' if len(renderCommands)==1 else f'_{i}'}.log"), 'a') as logFile:
                currentCommand = taskCommands[i]
                trueOutpath = None
                if 'ffmpeg' in currentCommand[0]:
                    if not overwrite_intermediate:
                        trueOutpath = currentCommand[-1]
                        if trueOutpath != finalOutpath:
                            assert trueOutpath.startswith(localBasepath)
                            tempFiles.append(trueOutpath)
                        if os.path.isfile(trueOutpath):
                            shouldSkip = True
                            try:
                                # compare 
                                videoInfo = getVideoInfo(trueOutpath)
                                duration = int(
                                    float(videoInfo['format']['duration']))
                                # if duration !=
                            except Exception as ex:
                                logger.detail(str(ex))
                                if renderLog is not None:
                                    renderLog(str(ex))
                            if shouldSkip:
                                logger.info(f"Skipping render to file {trueOutpath}, file already exists")
                                if renderLog is not None:
                                    renderLog(f"Skipping render to file {trueOutpath}, file already exists")
                                continue
                        else:
                            currentCommand[-1] = insertSuffix(
                                trueOutpath, '.temp')
                    else:  # overwrite_intermediate
                        currentOutpath = currentCommand[-1]
                        if currentOutpath.startswith(localBasepath):
                            tempFiles.append(currentOutpath)
                    # if task.renderConfig.logLevel > 0:
                    logger.info(f"Running render to file {trueOutpath if trueOutpath is not None else currentCommand[-1]} ...")
                    if renderLog is not None:
                        renderLog(f"Running render to file {trueOutpath if trueOutpath is not None else currentCommand[-1]} ...")

                # TODO: figure out how to replace with asyncio processes - need to run from one thread and interrupt from another

                try:
                    process = subprocess.Popen([str(command) for command in currentCommand],
                                               stdin=subprocess.DEVNULL,
                                               stdout=logFile,
                                               stderr=subprocess.STDOUT)
                    activeRenderSubprocess = process
                    returncode = process.wait()
                    activeRenderSubprocess = None
                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt detected, stopping active render!")
                    if renderLog is not None:
                        renderLog(
                        "Keyboard interrupt detected, stopping active render!")
                    process.kill()
                    process.wait()
                    logger.info("Render terminated!")
                    if renderLog is not None:
                        renderLog("Render terminated!")
                    return
                except Exception as ex:
                    logger.error(str(ex))
                    if renderLog is not None:
                        renderLog(str(ex))
                    returncode = -1
                    activeRenderSubprocess = None

                if returncode != 0:
                    hasError = True
                    if returncode != 130:  # ctrl-c on UNIX (?)
                        logger.error("Render errored! Printing current command:")
                        logger.error(formatCommand(currentCommand))
                        # logger.error(f"Render errored! Writing to log file {errorFilePath}")
                        # if renderLog is not None:
                        #     renderLog(f"Render errored! Writing to log file {errorFilePath}")
                        # setRenderStatus(task.mainStreamer,
                        #                 task.fileDate, 'ERRORED')
                        # with open(errorFilePath, 'a') as errorFile:
                        #     errorFile.write(
                        #         f'Errored on: {formatCommand(currentCommand)}\n')
                        #     errorFile.write(f'Full command list: ')
                        #     errorFile.write(' ;; '.join(
                        #         (formatCommand(renderCommand) for renderCommand in renderCommands)))
                        #     errorFile.write('\n\n')
                    break
                else:
                    if trueOutpath is not None:
                        shutil.move(currentCommand[-1], trueOutpath)
                        logger.info(f"Render to {trueOutpath} complete!")
                        if renderLog is not None:
                            renderLog(f"Render to {trueOutpath} complete!")
                    else:
                        logger.info(f"Render to {currentCommand[-1]} complete!")
                        if renderLog is not None:
                            renderLog(f"Render to {currentCommand[-1]} complete!")
        if not hasError:
            logger.info("Render task finished, cleaning up temp files:")
            logger.detail(tempFiles)
            setRenderStatus(task.mainStreamer, task.fileDate, 'FINISHED')
            if getConfig('main.copyFiles'):
                for file in (f for f in task.sourceFiles if f.videoFile.startswith(localBasepath)):
                    remainingRefs = decrFileRefCount(file.localVideoPath)
                    if remainingRefs == 0:
                        logger.detail(f"Removing local file {file}")
                        if renderLog is not None:
                            renderLog(f"Removing local file {file}")
                        os.remove(file)
            # intermediateFiles = set([command[-1] for command in renderCommands[:-1] if command[0].endswith('ffmpeg')])
            # for file in intermediateFiles:
            for file in tempFiles:
                logger.detail(f"Removing intermediate file {file}")
                if renderLog is not None:
                    renderLog(f"Removing intermediate file {file}")
                assert getConfig('basepath') not in file
                os.remove(file)
        renderQueue.task_done()
        if __debug__:
            break

def endRendersAndExit():
    logger.info("Shutting down!")
    print('Shutting down, please wait at least 15 seconds before manually killing...')
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if activeRenderSubprocess is not None:
        logger.info("Terminating render thread")
        print("Terminating render thread")
        activeRenderSubprocess.terminate()
        activeRenderSubprocess.wait(10)
        if activeRenderSubprocess.poll() is None:
            logger.info("Terminating render thread did not complete within 10 seconds, killing instead")
            print(
                "Terminating render thread did not complete within 10 seconds, killing instead")
            activeRenderSubprocess.kill()
            activeRenderSubprocess.wait()
        if activeRenderSubprocess.poll() is not None:
            logger.info("Active render stopped successfully")
            print("Active render stopped successfully")
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    print("Stopping!")
    logger.info("Stopping!")
    sys.exit(0)


if getConfig('internal.ENABLE_URWID'):
    import UrwidUI.UrwidMain
    renderThread = threading.Thread(target=renderWorker, kwargs={'renderLog':UrwidUI.UrwidMain.renderText.addLine})
    renderThread.daemon = True
else:
    renderThread = threading.Thread(target=renderWorker)
    renderThread.daemon = True
    