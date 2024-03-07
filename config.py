# +
import os
from datetime import timezone, time, timedelta
streamersParseChatList = ('ChilledChaos', 'ZeRoyalViking')

basepath = '/mnt/pool2/media/Twitch Downloads/'
#localBasepath = '/mnt/scratch1/'
localBasepath = '/mnt/pool1/media/downloads/'
outputDirectory = "Rendered Multiviews"

ENABLE_URWID = False

mainStreamers = ['ChilledChaos',]# 'ZeRoyalViking']
#globalAllStreamers = [name for name in os.listdir(basepath) if
#                      (name not in ("NA", outputDirectory) and 
#                       os.path.isdir(os.path.join(basepath, name)))]
#secondaryStreamers = [name for name in globalAllStreamers if name not in mainStreamers]

streamerAliases = {'AphexArcade':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'APlatypus':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'ArtificialActr':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'BonsaiBroz':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm',
                                'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   #'BryceMcQuaid':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'chibidoki':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                'https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy',],
                   'Courtilly':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'CheesyBlueNips':['Cheesy'],
                   'ChilledChaos':['Chilled'],
                   'CrashVS':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'DooleyNotedGaming':['Jeremy'], 
                   'ElainaExe':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'emerome':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'FlanelJoe':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'HeckMuffins':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Junkyard129':['Junkyard', 'Junk',
                                  'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'KaraCorvus':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                #' Kara,',
                                ],
                   #'KDoolz':['Kat'],
                   'Kn0vis':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Kruzadar':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'
                               'https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy',],
                   'KYR_SP33DY':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm',
                                 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                 'https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy',
                                 'Speedy'],
                   'LarryFishburger':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                      'https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy',
                                     'Larry'],
                   'MG4R':['Greg', 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'MicheleBoyd':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'ozzaworld':['ozza'],
                   'PastaroniRavioli':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                      'https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy',
                                      'Pasta', 'Pastaroni'],
                   'Skadj':['https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy'],
                   'SlackATK':['https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy'],
                   'SideArms4Reason':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm', #hacky override for Twitch Rivals 12/7/23
                                      'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                      'https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy',
                                      'SideArms'],
                   'TayderTot':['https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy'],
                   'TheRealShab':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1',
                                 'Shab'],
                   'ToastyFPS':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'TomFawkes':['Tom Fawks'],
                   'VikramAFC':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Your__Narrator': ['YourNarrator'],
                   'Zentreya':['https://clips.twitch.tv/DarlingSeductiveSamosaCharlieBitMe-oItZEhTSQrnUFgMy'],
                  }

nongroupGames = ('Just Chatting', "I'm Only Sleeping")
ffmpegPath='' #Use PATH #'/home/ubuntu/ffmpeg-cuda/ffmpeg/'

characterReplacements = {'?':'？', '/':'', '\\':''}

threadCount = os.cpu_count()

#videoExt = '.mp4'
videoExts = ['.mp4', '.mkv']
infoExt = '.info.json'
chatExt = '.rechat.twitch-gql-20221228.json'
otherExts = ['.description', '.jpg']
videoIdRegex = r"(v?[\d]{9,11})" #r"(v[\d]+)"

DEFAULT_DATA_FILEPATH = r'./knownFiles.pickle' #r'/home/ubuntu/Documents/MultiTwitchRenderer/allTwitchFiles.pickle'

REDUCED_MEMORY = False

EST_TIMEZONE = timezone(timedelta(hours=-5))
CST_TIMEZONE = timezone(timedelta(hours=-6))
MST_TIMEZONE = timezone(timedelta(hours=-7))
PST_TIMEZONE = timezone(timedelta(hours=-8))
UTC_TIMEZONE = timezone(timedelta(hours=0))
LOCAL_TIMEZONE = CST_TIMEZONE
DAY_START_TIME = time(0, 0, 0, tzinfo=LOCAL_TIMEZONE)

outputResolutions = [None, (1920,1080), (3840,1080), (3840,2160), (3840,2160), (3840,2160), (3840,2160), (4480,2520)]
outputBitrates = [None,    "6M",        "12M",       "20M",       "25M",       "25M",       "30M",       "40M"]

errorFilePath = r'./erroredCommands.log'
statusFilePath = r'./renderStatuses.pickle'
logFolder = r'./logs/'

COPY_FILES = False
DEFAULT_MAX_LOOKBACK=timedelta(days=30)

minimumSessionWorkerDelay = timedelta(hours=3)

DEFAULT_MONITOR_STREAMERS = ('ChilledChaos', )

DEFAULT_OVERWRITE_INTERMEDIATE = True
DEFAULT_OVERWRITE_OUTPUT = False
DEFAULT_LOOKBACK_DAYS = 14

RENDER_CONFIG_DEFAULTS = {
    'drawLabels': False,
    'startTimeMode': 'mainSessionStart',
    'endTimeMode': 'mainSessionEnd',
    'logLevel': 0,
    'sessionTrimLookback': 0,
    'sessionTrimLookahead': 0,
    'sessionTrimLookbackSeconds': 0,
    'sessionTrimLookaheadSeconds': 600,
    'minGapSize': 0,
    'outputCodec': 'libx264',
    'encodingSpeedPreset': 'medium',
    'useHardwareAcceleration': 0,
    'maxHwaccelFiles': 0,
    'minimumTimeInVideo': 900,
    'cutMode': 'chunked',
    'useChat': True,
}
# -

gameAliases = {'Among Us':('Town of Us', r"TOWN OF US PROXY CHAT | Among Us w/ Friends"),
               'Tabletop Simulator': ('Board Games',),
               'Suika Game': ('Suika',),
               'Monopoly Plus': ('Monopoly',)}

