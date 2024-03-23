from typing import Dict, List
from SharedUtils import convertToDatetime
#from SourceFile import SourceFile
import json
import re
from datetime import datetime
from fuzzysearch import find_near_matches

if __debug__:
    from config import *
exec(open("config.py").read(), globals())

def parsePlayersFromGroupMessage(message: str):
    players = []
    messageLowercase = message.lower()
    for streamer in globalAllStreamers:
        fuzzymatches = find_near_matches(
            streamer.lower(), messageLowercase, max_l_dist=len(streamer)//5)
        if len(fuzzymatches) > 0:
            players.append(streamer)
        elif streamer in streamerAliases.keys():
            for alias in streamerAliases[streamer]:
                fuzzymatches = find_near_matches(
                    alias.lower(), messageLowercase, max_l_dist=len(alias)//5)
                if len(fuzzymatches) > 0:
                    players.append(streamer)
                    break
    return players

class ParsedChat:
    def __init__(self, parentFile: 'SourceFile', chatFile: str):
        self.parentFile = parentFile
        with open(chatFile) as chatFileContents:
            chatJson = json.load(chatFileContents)
        # print(chatFile)
        nightbotGroupComments = []
        groupEditComments = []
        groups: List[Dict[str, datetime | List[str]]] = []
        lastCommandComment = None
        # self.chatJson = chatJson
        # print(f"Parsed {len(chatJson)} comments")
        for comment in chatJson:
            commenter = comment['commenter']
            user = commenter['displayName'] if commenter is not None else None
            messageFragments = comment['message']['fragments']
            if len(messageFragments) == 0:
                continue
            firstMessageFrag = messageFragments[0]['text']
            fullMessage = " ".join((frag['text'] for frag in messageFragments))
            offset = comment['contentOffsetSeconds']
            timestamp = comment['createdAt']
            if user == 'Nightbot':
                if lastCommandComment is not None and offset - lastCommandComment['contentOffsetSeconds'] < 4:
                    nightbotGroupComments.append(comment)
                    group = parsePlayersFromGroupMessage(fullMessage)
                    # print(fullMessage)
                    # print(group)
                    if self.parentFile.streamer in group:
                        group.remove(self.parentFile.streamer)
                    convertedTime = datetime.fromisoformat(timestamp)
                    # if len(groups) == 0 or set(group) != set(groups[-1].group):
                    groups.append({'group': group, 'time': convertedTime})
                lastCommandComment = None
            else:
                if firstMessageFrag.lower().strip() in ('!who', '!group'):
                    lastCommandComment = comment
                else:
                    sub = re.sub(r'\s+', ' ', fullMessage.lower())
                    if (any((badge['setID'] == 'moderator' for badge in comment['message']['userBadges'])) and
                            (sub.startswith('!editcom !group') or sub.startswith('!commands edit !group'))):
                        groupEditComments.append(comment)
                        newCommandText = fullMessage[6 +
                                                     fullMessage.lower().index('!group'):]
                        group = parsePlayersFromGroupMessage(newCommandText)
                        if self.parentFile.streamer in group:
                            group.remove(self.parentFile.streamer)
                        # print(fullMessage)
                        # print(newCommandText)
                        # print(sorted(group), end='\n\n')
                        convertedTime = datetime.fromisoformat(timestamp)
                        groups.append({'group': group, 'time': convertedTime})
        self.nightbotGroupComments = nightbotGroupComments
        self.groupEditComments = groupEditComments
        self.groups = groups

    def getGroupAtTimestamp(self, timestamp: int | float | str | datetime) -> List[str]:
        dt = convertToDatetime(timestamp)
        lastMatch = []
        for group in self.groups:
            if group['time'] < dt:
                lastMatch = group['group']
            else:
                break
        return lastMatch

    def getAllPlayersOverRange(self, startTimestamp: int | float | str | datetime, endTimestamp: int | float | str | datetime) -> List[str]:
        start = convertToDatetime(startTimestamp)
        end = convertToDatetime(endTimestamp)
        allPlayers = set()
        lastMatch = []
        for group in self.groups:
            if len(lastMatch) == 0 and group['time'] < start:
                # get last group before this range, in case no commands are found
                lastMatch = group['group']
            if start < group['time'] < end:
                allPlayers.update(group['group'])  # command is within range,
        return allPlayers if len(allPlayers) > 0 else lastMatch
