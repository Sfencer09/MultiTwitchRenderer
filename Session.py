
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Tuple

from SharedUtils import getTimeOverlap
if TYPE_CHECKING:
    from SourceFile import SourceFile


class Session:
    def __init__(self, file: 'SourceFile', game: str, startTimestamp: int | float, endTimestamp: int | float):
        self.startTimestamp = startTimestamp
        self.endTimestamp = endTimestamp
        self.file = file
        self.game = game

    def hasOverlap(self, cmp: 'Session', useChat=True, targetRange=None) -> bool:
        if self.startTimestamp > cmp.endTimestamp or self.endTimestamp < cmp.startTimestamp:
            return False
        if targetRange is None:
            if useChat:
                if self.file.parsedChat is not None:
                    selfPlayers = self.file.parsedChat.getAllPlayersOverRange(
                        self.startTimestamp-15, self.endTimestamp)
                    if cmp.file.streamer in selfPlayers:
                        return True
                if cmp.file.parsedChat is not None:
                    cmpPlayers = cmp.file.parsedChat.getAllPlayersOverRange(
                        cmp.startTimestamp-15, self.endTimestamp)
                    if self.file.streamer in cmpPlayers:
                        return True
            return self.game == cmp.game and (not useChat or (self.file.parsedChat is None and cmp.file.parsedChat is None))
        else:
            rangeStart, rangeEnd = targetRange
            if self.endTimestamp < rangeStart or cmp.endTimestamp < rangeStart or self.startTimestamp > rangeEnd or cmp.startTimestamp > rangeEnd:
                return False
            overlapStart = max(self.startTimestamp,
                               cmp.startTimestamp, rangeStart)
            overlapEnd = min(self.endTimestamp, cmp.endTimestamp, rangeEnd)
            overlapLength = overlapEnd - overlapStart
            # if overlapLength < (rangeEnd - rangeStart) / 2:
            #    return False
            if useChat:
                if self.file.parsedChat is not None:
                    selfPlayers = self.file.parsedChat.getAllPlayersOverRange(
                        overlapStart, overlapEnd)
                    if cmp.file.streamer in selfPlayers:
                        return True
                if cmp.file.parsedChat is not None:
                    cmpPlayers = cmp.file.parsedChat.getAllPlayersOverRange(
                        overlapStart, overlapEnd)
                    if self.file.streamer in cmpPlayers:
                        return True
            return self.game == cmp.game and (not useChat or (self.file.parsedChat is None and cmp.file.parsedChat is None))
            # raise Exception("Not implemented yet")

    def hasOverlapV2(self, cmp: 'Session', useChat=True, targetRange:None | Tuple[int, int]=None, inclusionThreshold:float=0.5) -> bool:
        assert inclusionThreshold <= 0.95
        assert targetRange is None or len(targetRange) == 2, f"Invalid target range: {targetRange}"
        if targetRange is None:
            overlapTimes = getTimeOverlap(self.startTimestamp, self.endTimestamp, cmp.startTimestamp, cmp.endTimestamp)
        else:
            overlapTimes = getTimeOverlap(self.startTimestamp, self.endTimestamp, cmp.startTimestamp, cmp.endTimestamp, *targetRange)
        if overlapTimes is None:
            return False
        # If we didn't return False, we at least have some time overlap
        if useChat:
            overlapStart, overlapEnd = overlapTimes
            def hasChatOverlap(groupsList:List[Dict[str, datetime|List[str]]], matchStreamer:str):
                sortedGroups = sorted(groupsList, key=lambda x: x['time'])
                if len(sortedGroups) == 0:
                    return False
                if overlapEnd < sortedGroups[0]['time'].timestamp():
                    return matchStreamer in sortedGroups[0]['group']
                if sortedGroups[-1]['time'].timestamp() < overlapStart:
                    return matchStreamer in sortedGroups[-1]['group']
                # If we haven't returned yet, we have at least one group entry within the overlap time,
                # we need to calculate how much of the overlap time has the matching streamer
                overlapDuration = overlapEnd - overlapStart
                inclusionDuration: float = 0
                groupOverlapStart = None
                groupOverlapEnd = None
                for i in range(len(sortedGroups)):
                    entry = sortedGroups[i]
                    if overlapStart <= entry['time'].timestamp() < overlapEnd:
                        if groupOverlapStart is None:
                            groupOverlapStart = i
                        groupOverlapEnd = i
                assert groupOverlapStart is not None and groupOverlapEnd is not None
                if groupOverlapStart > 0:
                    leadingGroupEntry = sortedGroups[groupOverlapStart-1]
                else:
                    leadingGroupEntry = sortedGroups[groupOverlapStart]
                if matchStreamer in leadingGroupEntry['group']:
                    inclusionDuration += leadingGroupEntry['time'].timestamp() - overlapStart
                for i in range(groupOverlapStart, groupOverlapEnd-1):
                    entry1 = sortedGroups[i]
                    entry2 = sortedGroups[i+1]
                    if matchStreamer in entry1['group']:
                        inclusionDuration += entry2['time'].timestamp() - entry1['time'].timestamp()

                trailingGroupEntry = sortedGroups[groupOverlapEnd]
                if matchStreamer in trailingGroupEntry['group']:
                    inclusionDuration += overlapEnd - trailingGroupEntry['time'].timestamp()
                inclusionFraction = inclusionDuration / overlapDuration
                return inclusionFraction >= inclusionThreshold
            
            if self.file.parsedChat is not None:
                foundOverlap = hasChatOverlap(self.file.parsedChat, cmp.file.streamer)
                if foundOverlap:
                    return True
            if cmp.file.parsedChat is not None:
                foundOverlap = hasChatOverlap(cmp.file.parsedChat, self.file.streamer)
                return foundOverlap
            return self.game == cmp.game
        else:
            return self.game == cmp.game

    def __repr__(self):
        return f"Session(game=\"{self.game}\", startTimestamp={self.startTimestamp}, endTimestamp={self.endTimestamp}, file=\"{self.file}\")"
