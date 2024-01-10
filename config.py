# +
import os
from datetime import timezone, time, timedelta
streamersParseChatList = ('ChilledChaos', 'ZeRoyalViking')

basepath = '/mnt/pool2/media/Twitch Downloads/'
#localBasepath = '/mnt/scratch1/'
localBasepath = '/mnt/pool1/media/downloads/'
outputDirectory = "Rendered Multiviews"

mainStreamers = ['ChilledChaos',]# 'ZeRoyalViking']
globalAllStreamers = [name for name in os.listdir(basepath) if
                      (name not in ("NA", outputDirectory) and 
                       os.path.isdir(os.path.join(basepath, name)))]
secondaryStreamers = [name for name in globalAllStreamers if name not in mainStreamers]

streamerAliases = {'AphexArcade':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'APlatypus':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'ArtificialActr':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'BonsaiBroz':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm',
                                'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   #'BryceMcQuaid':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'chibidoki':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Courtilly':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'CrashVS':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'DooleyNotedGaming':['Jeremy'], 
                   'ElainaExe':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'emerome':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'FlanelJoe':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'HeckMuffins':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Junkyard129':['Junkyard', 'Junk', 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'KaraCorvus':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Kn0vis':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Kruzadar':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'KYR_SP33DY':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm',
                                 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'LarryFishburger':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'MG4R':['Greg', 'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'MicheleBoyd':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'PastaroniRavioli':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'SideArms4Reason':['https://schedule.twitchrivals.com/events/party-animals-showdown-ii-presented-by-venus-JgLwm', #hacky override for Twitch Rivals 12/7/23
                                      'https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'TheRealShab':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'ToastyFPS':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'VikramAFC':['https://twitter.com/ChilledChaos/status/1737167373797413287/photo/1'],
                   'Your__Narrator': ['YourNarrator']}

nongroupGames = ('Just Chatting', "I'm Only Sleeping")
ffmpegPath='' #Use PATH #'/home/ubuntu/ffmpeg-cuda/ffmpeg/'

characterReplacements = {'?':'？', '/':'', '\\':''}

threadCount = 16 #os.cpu_count()

defaultSetPTS = "PTS-STARTPTS"
videoSetPTS = "N/FRAME_RATE/TB"
audioSetPTS = "N/SR/TB"
apts = defaultSetPTS
vpts = defaultSetPTS

videoExt = '.mp4'
infoExt = '.info.json'
chatExt = '.rechat.twitch-gql-20221228.json'
otherExts = ['.description', '.jpg']
videoIdRegex = r"(v[\d]+)"

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

minimumSessionWorkerDelay = timedelta(hours=2)

DEFAULT_MONITOR_STREAMERS = ('ChilledChaos', )

DEFAULT_OVERWRITE_INTERMEDIATE = True
DEFAULT_OVERWRITE_OUTPUT = False

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
