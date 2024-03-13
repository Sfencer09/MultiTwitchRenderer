from typing import TYPE_CHECKING

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

    def __repr__(self):
        return f"Session(game=\"{self.game}\", startTimestamp={self.startTimestamp}, endTimestamp={self.endTimestamp}, file=\"{self.file}\")"
