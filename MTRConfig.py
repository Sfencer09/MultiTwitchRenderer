import os
import re
import argparse
import subprocess
import tomllib
import MTRLogging
from datetime import time as datetimetime

logger = MTRLogging.getLogger('MainConfig')

from schema import Schema, Optional, Or, And, Use, Regex

HW_DECODE = 1
HW_INPUT_SCALE = 2
HW_OUTPUT_SCALE = 4
HW_ENCODE = 8

def configFileType(val):
    with open(val, 'rb') as file:
        tomllib.load(file)
        return val

argParser = argparse.ArgumentParser()
argParser.add_argument('--config-file',
                       help='Path to TOML config file',
                       dest='configFilePath',
                       type=configFileType,
                       default='./config.toml')
args, _ = argParser.parse_known_args()
configFilePath = args.configFilePath

trueStrings = ('t', 'y', 'true', 'yes')

hardwareAccelDeviceSchema = {
    'mask': (lambda x: x & (HW_DECODE | HW_ENCODE | HW_INPUT_SCALE | HW_OUTPUT_SCALE) == x),
    Optional('priority', default=0): int,
    Optional('maxDecodeStreams', default=0): And(int, lambda x: x >= 0)
}

def _isDevicePath(path: str):
    if os.path.isdir(path) or os.path.isfile(path):
        return False # Device paths are not considered files, and we can't use directories
    try:
        os.stat(path)
    except OSError:
        return False
    return True

#Unlike the one in RenderConfig, this one only validates the fields, it does not perform complex conversions
renderConfigSchema = {
    Optional('drawLabels', default=True): #defaultRenderConfig['drawLabels']):
    Or(bool, Use(lambda x: x.lower() in trueStrings)),
    Optional('startTimeMode', default='mainSessionStart'): #defaultRenderConfig['startTimeMode']):
    lambda x: x in ('mainSessionStart', 'allOverlapStart'),
    Optional('endTimeMode', default='mainSessionEnd'): #defaultRenderConfig['endTimeMode']):
    lambda x: x in ('mainSessionEnd', 'allOverlapEnd'),
    Optional('logLevel', default=0): #defaultRenderConfig['logLevel']):
    And(Use(int), lambda x: 0 <= x <= 4),  # max logLevel = 4
    Optional('sessionTrimLookback', default=0): #defaultRenderConfig['sessionTrimLookback']):
    # TODO: convert from number of segments to number of seconds. Same for lookahead
    Use(int),
    Optional('sessionTrimLookahead', default=0): #defaultRenderConfig['sessionTrimLookahead']):
    And(Use(int), lambda x: x >= 0),
    Optional('sessionTrimLookbackSeconds', default=0): #defaultRenderConfig['sessionTrimLookbackSeconds']):
    And(Use(int), lambda x: x >= 0),  # Not implemented yet
    Optional('sessionTrimLookaheadSeconds', default=0): #defaultRenderConfig['sessionTrimLookaheadSeconds']):
    And(Use(int), lambda x: x >= 0),
    # Optional(Or(Optional('sessionTrimLookback', default=0),
    # Optional('sessionTrimLookbackSeconds', default=0), only_one=True), ''): And(int, lambda x: x>=-1),
    # Optional(Or(Optional('sessionTrimLookahead', default=0),
    # Optional('sessionTrimLookaheadSeconds', default=600), only_one=True): And(int, lambda x: x>=0),
    Optional('minGapSize', default=0): #defaultRenderConfig['minGapSize']):
    And(Use(int), lambda x: x >= 0),
    Optional('outputCodec', default='libx264'): #defaultRenderConfig['outputCodec']):
    lambda x: x in acceptedOutputCodecs,
    Optional('encodingSpeedPreset', default='medium'): #defaultRenderConfig['encodingSpeedPreset']):
    lambda x: x in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium',
                    'slow', 'slower', 'veryslow') or x in [f'p{i}' for i in range(1, 8)],
    #Optional('useHardwareAcceleration', default=0): #defaultRenderConfig['useHardwareAcceleration']):
    #And(Use(int), lambda x: x & 15 == x),
    Optional('hardwareAccelDevices', default={}):
        Or({},
           hardwareAccelDeviceSchema, 
           {Or(And(Use(int), lambda x: x>=0),
               And(str, _isDevicePath)):
                   hardwareAccelDeviceSchema}),
    # And(Use(int), lambda x: 0 <= x < 16), #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale input, bit 3(4)=scale output, bit 4(8)=encode
    Optional('maxHwaccelFiles', default=0): #defaultRenderConfig['maxHwaccelFiles']):
    And(Use(int), lambda x: x >= 0),
    Optional('minimumTimeInVideo', default=0): #defaultRenderConfig['minimumTimeInVideo']):
    And(Use(int), lambda x: x >= 0),
    Optional('cutMode', default='chunked'): #defaultRenderConfig['cutMode']):
    lambda x: x in ('chunked', ),  # 'trim', 'segment'),
    Optional('useChat', default=True): #defaultRenderConfig['useChat']):
    Or(bool, Use(lambda x: x.lower() in trueStrings)),
    Optional('preciseAlign', default=True): #defaultRenderConfig['preciseAlign']):
    Or(bool, Use(lambda x: x.lower() in trueStrings)),
}


def isWriteableDir(prospectiveDir):
    return os.path.isdir(prospectiveDir) and os.access(prospectiveDir, os.W_OK)

def isCreateableDir(prospectiveDir):
    ...

def isWriteableFile(prospectiveFile):
    # if file exists, test if it's writeable. If it doesn't exist, test if the parent directory is writeable
    return os.access(prospectiveFile, os.W_OK) if os.path.isfile(prospectiveFile) else os.access(os.path.dirname(prospectiveFile), os.W_OK)

streamerNameRegex = r"[a-zA-Z0-9][a-zA-Z0-9_]{3,24}"

def isValidStreamerName(prospectiveName):
    return re.fullmatch(streamerNameRegex, prospectiveName)

timezoneRegex = r"[-+][0-9]{1,2}:[0-9]{2}"

def convertTimezoneString(prospectiveTz):
    if not re.fullmatch(timezoneRegex, prospectiveTz):
        raise ValueError(f'Timezone string "{prospectiveTz}" does not match regex "{timezoneRegex}"')
    tempTime = datetimetime.fromisoformat(f'00:00:00{prospectiveTz}')
    return tempTime.tzinfo

acceptedOutputCodecs = ['libx264', 'libx265']
hardwareOutputCodecs = []

def isAcceptedOutputCodec(codec:str):
    return codec in acceptedOutputCodecs

def isHardwareOutputCodec(codec:str):
    return codec in hardwareOutputCodecs

configSchema = Schema({
    'main': {
        'basepath': isWriteableDir,
        'localBasepath': isWriteableDir,
        Optional('outputDirectory', default='Rendered_Multiviews'):
            And(str, lambda val: all((x not in val for x in ("\\/")))),
        Optional('streamersParseChatList', default=[]):
            [isValidStreamerName],
        Optional('dataFilepath', default='./knownFiles.pickle'):
            isWriteableFile,
        Optional('nongroupGames', default=['Just Chatting', "I'm Only Sleeping"]):
            [str],
        Optional('ffmpegPath', default=''):
            And(str, lambda x: x == '' or x[-1]=='/'),
        'localTimezone':
            And(str, Use(convertTimezoneString)),
        #Optional('errorFilePath', default='./erroredCommands.log'):
        #    str,
        Optional('statusFilePath', default='./renderStatuses.pickle'):
            str,
        Optional('logFolder', default='./logs/'):
            str,
        Optional('copyFiles', default=False):
            bool,
        'minimumSessionWorkerDelayHours':
            And(int, lambda x: x > 0),
        'monitorStreamers':
            [isValidStreamerName],
        Optional('overwriteIntermediateFiles', default=True):
            bool,
        Optional('overwriteOutputFiles', default=False):
            bool,
        'sessionLookbackDays':
            And(int, lambda x: x>=0),
        'defaultRenderConfig': 
            renderConfigSchema,
    },
    'internal': {
        Optional('threadCount', default=0):
            And(int, lambda x: x>=0),
        Optional('videoExts', default= [ ".mp4", ".mkv" ]):
            And([str], lambda x: len(x) >= 2 and all((ext.startswith('.') for ext in x))),
        Optional('infoExt', default= '.info.json'):
            And(str, lambda x: len(x) >= 2 and x.startswith('.')),# and x.endswith('.json')),
        Optional('chatExt', default= '.rechat.twitch-gql-20221228.json'):
            And(str, lambda x: len(x) >= 2 and x.startswith('.')),# and x.endswith('.json')
        Optional('otherExts', default= ['.description', '.jpg']):
            And([str], lambda x: all((len(ext) >= 2 and ext.startswith('.') for ext in x))),
        # Regex of the video id within the filename. Should be exact enough to avoid false positives
        Optional('videoIdRegex', default= "(v?[\\d]{9,11})"):
            str,
        Optional('characterReplacements', default = {'?':'？', '/':'⧸', '\\':'⧹', ':':'：', '<':'＜', '>':'＞'}):
            And({str:str}, lambda x: all((len(key)==1 for key in x.keys()))),
        Optional('reducedFfmpegMemory', default=False):
            bool,
        Optional('ENABLE_URWID', default=False):
            And(bool, False),
        Optional('outputResolutions', default=[[],
                    [1920,1080],
                    [3840,1080],
                    [3840,2160],
                    [3840,2160],
                    [3840,2160],
                    [3840,2160],
                    [4480,2520]]):
            Or([], [lambda x: len(x) == 0 or (len(x) == 2 and all((int(y)==y) for y in x))]),
        Optional('outputBitrates', default=["",
                                            "6M",
                                            "12M",
                                            "20M",
                                            "25M",
                                            "25M",
                                            "30M",
                                            "40M"]):
            ["", Regex('[0-9]+(\\.[0-9]+)?[KMG]')]
    },
    Optional('gameAliases', default={}):
        {str: [str]},
    Optional('streamerAliases', default={}):
        {str: [str]},
})

__softwareEncodingPresets = ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow')
__nvidiaEncodingPresets = tuple((f"p{n}" for n in range(1, 8)))
__qsvEncodingPresets = ('veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow')
# See AMD/Mesa section at https://trac.ffmpeg.org/wiki/Hardware/VAAPI#AMDMesa
__amdEncodingPresets = tuple((str(i) for i in range(1, 8)))
__h264DefaultOptions = ("-profile:v", "high",
                        # "-maxrate",outputBitrates[maxTileWidth],
                        # "-bufsize","4M",
                        "-preset", "{preset}",
                        "-crf", "22",
                        )
__h264DefaultReducedMemoryOptions = tuple(list(__h264DefaultOptions) + ['-rc-lookahead', '20', '-g', '60'])
__h265DefaultOptions = ("-preset", "{preset}",
                        "-crf", "26",
                        "-tag:v", "hvc1"
                        )
__h265DefaultReducedMemoryOptions = __h265DefaultOptions


HWACCEL_VALUES = {
    'NVIDIA': {
        'scale_filter': '_npp',
        'pad_filter': '_opencl',
        'xstack_filter': None,
        'upload_filter': '_cuda',
        'decode_input_options': ('-threads', '1', '-c:v', 'h264_cuvid'),
        'scale_input_options': ('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'),
        #'encode_codecs': ('h264_nvenc', 'hevc_nvenc'), # to be deprecated
        'encode_codec_options': {
            'h264_nvenc': {
                'validPresets': __nvidiaEncodingPresets,
                'defaultSettings': __h264DefaultOptions,
                'reducedMemorySettings': __h264DefaultReducedMemoryOptions,
            },
            'hevc_nvenc': {
                'validPresets': __nvidiaEncodingPresets,
                'defaultSettings': __h264DefaultOptions,
                'reducedMemorySettings': __h264DefaultReducedMemoryOptions,
            }
        }
    },
    'AMD': {
        'scale_filter': '',
        'pad_filter': '',
        'xstack_filter': None,
        'upload_filter': '',
        # ('-hwaccel', 'dxva2'), #for AV1 inputs only: ('-extra_hw_frames', '10'),
        'decode_input_options': ('-hwaccel', 'd3d11va'),
        'scale_input_options': None,
        #'encode_codecs': ('h264_amf', 'hevc_amf'), # to be deprecated
        'encode_codec_options': {
            'h264_amf': {
                'validPresets': __amdEncodingPresets,
                'defaultSettings': ("-profile:v", "high",
                        # "-maxrate",outputBitrates[maxTileWidth],
                        # "-bufsize","4M",
                        "-compression_level", "{preset}",
                        "-crf", "22",
                        ),
                'reducedMemorySettings': ("-profile:v", "high",
                        # "-maxrate",outputBitrates[maxTileWidth],
                        # "-bufsize","4M",
                        "-compression_level", "{preset}",
                        "-crf", "22",
                        '-rc-lookahead', '20',
                        '-g', '60',
                        ),
            },
            'hevc_amf': {
                'validPresets': __amdEncodingPresets,
                'defaultSettings': ("-compression_level", "{preset}",
                        "-crf", "26",
                        "-tag:v", "hvc1"
                        ),
                'reducedMemorySettings': ("-compression_level", "{preset}",
                        "-crf", "26",
                        "-tag:v", "hvc1"
                        ),
            }
        }
    },
    'Intel': {
        'scale_filter': '_qsv',
        'pad_filter': '_qsv',
        'xstack_filter': '_qsv', # Not implemented yet
        'upload_filter': '=extra_hw_frames=64,format=qsv',
        'decode_input_options': ('-hwaccel', 'qsv', '-c:v', 'h264_qsv'),
        'scale_input_options': None,
        #'encode_codecs': ('h264_qsv', 'hevc_qsv'), # to be deprecated
        'encode_codec_options': {
            'h264_qsv': {
                'validPresets': __qsvEncodingPresets,
                'defaultSettings': ("-profile:v", "high",
                        # "-maxrate",outputBitrates[maxTileWidth],
                        # "-bufsize","4M",
                        "-preset", "{preset}",
                        "-q", "22",
                        ),
                'reducedMemorySettings': ("-profile:v", "high",
                        # "-maxrate",outputBitrates[maxTileWidth],
                        # "-bufsize","4M",
                        "-preset", "{preset}",
                        "-q", "22",
                        ),
            },
            'hevc_qsv': {
                'validPresets': __qsvEncodingPresets,
                'defaultSettings': __h265DefaultOptions,
                'reducedMemorySettings': __h265DefaultReducedMemoryOptions,
            },
            'av1_qsv':{
                'validPresets': __qsvEncodingPresets,
                'defaultSettings': ("-preset", "{preset}",
                                    "-profile", "main",
                                    "-crf", "30"),
                'reducedMemorySettings': ("-preset", "{preset}",
                                        "-profile", "main",
                                        "-crf", "30"),
            }
        }
    },
    None: {
        'scale_filter': '',
        'pad_filter': '',
        'upload_filter': '',
        'decode_input_options': ('-hwaccel', 'qsv', '-c:v', 'h264_qsv'),
        'scale_input_options': None,
        #'encode_codecs': ('libx264', 'libx265'),#'libsvtav1'),  # to be deprecated
        'encode_codec_options': {
            'libx264': {
                'validPresets': __softwareEncodingPresets,
                'defaultSettings': __h264DefaultOptions,
                'reducedMemorySettings':__h264DefaultReducedMemoryOptions,
            },
            'libx265': {
                'validPresets': __softwareEncodingPresets,
                'defaultSettings': __h265DefaultOptions,
                'reducedMemorySettings':__h265DefaultReducedMemoryOptions,
            },
            'libsvtav1': {
                'validPresets': [str(i) for i in range(9)],
                'defaultPresets': ("-preset", "{preset}",
                                   "-crf", "30"),
                'reducedMemorySettings':  ("-preset", "{preset}",
                                           "-crf", "30")
            }
        }
    }
}
HWACCEL_BRAND = None
HWACCEL_FUNCTIONS = 0
ACTIVE_HWACCEL_VALUES = None

def getHasHardwareAceleration(ffmpegPath:str=""):
    SCALING = HW_INPUT_SCALE | HW_OUTPUT_SCALE
    process1 = subprocess.run(
        [f"{ffmpegPath}ffmpeg", "-version"], capture_output=True)
    logger.info(process1.stdout.decode())
    try:
        process2 = subprocess.run(
            ["nvidia-smi", "-q", "-d", "MEMORY,UTILIZATION"], capture_output=True)
        nvidiaSmiOutput = process2.stdout.decode()
        logger.info(nvidiaSmiOutput)
        logger.info(process2.returncode)
        if process2.returncode == 0:
            encoding = False
            decoding = False
            rowCount = 0
            for row in nvidiaSmiOutput.split('\n'):
                if 'Encoder' in row:
                    encoding = 'N/A' not in row
                elif 'Decoder' in row:
                    decoding = 'N/A' not in row
                rowCount += 1
            logger.info(f"Row count: {rowCount}")
            mask = SCALING
            if decoding:
                mask |= HW_DECODE
            if encoding:
                mask |= HW_ENCODE
            return ('NVIDIA', mask)
    except Exception as ex:
        pass
    try:
        process3 = subprocess.run(["rocm-smi", "--json"], capture_output=True)
        amdSmiOutput = process3.stdout.decode()
        logger.info(amdSmiOutput)
        logger.info(process3.returncode)
        if process3.returncode == 0:
            logger.info("Parsing AMD HW acceleration from rocm-smi not implemented yet, assuming all functions available")
            return ('AMD', HW_DECODE | HW_ENCODE)
    except Exception as ex:
        pass
    return (None, 0)

def loadHardwareAcceleration(ffmpegPath:str=""):
    global HWACCEL_BRAND
    global HWACCEL_FUNCTIONS
    global ACTIVE_HWACCEL_VALUES
    global acceptedOutputCodecs
    global hardwareOutputCodecs
    HWACCEL_BRAND, HWACCEL_FUNCTIONS = getHasHardwareAceleration()
    if HWACCEL_BRAND is not None:
        logger.info(f'{HWACCEL_BRAND} hardware video acceleration detected')
        logger.info(f'Functions:')
        if HWACCEL_FUNCTIONS & HW_DECODE != 0:
            logger.info("    Decode")
        if HWACCEL_FUNCTIONS & (HW_INPUT_SCALE | HW_OUTPUT_SCALE) != 0:
            logger.info("    Scaling")
        if HWACCEL_FUNCTIONS & HW_ENCODE != 0:
            logger.info("    Encode")
    else:
        logger.info('No hardware video decoding detected!')

    #if HWACCEL_BRAND is not None:
    ACTIVE_HWACCEL_VALUES = HWACCEL_VALUES[HWACCEL_BRAND]
    #else:
    #    ACTIVE_HWACCEL_VALUES = None


    if ACTIVE_HWACCEL_VALUES is not None:
        hardwareOutputCodecs = ACTIVE_HWACCEL_VALUES['encode_codecs']
        acceptedOutputCodecs.extend(hardwareOutputCodecs)
    else:
        hardwareOutputCodecs = []

def validateHwaccelFunctions(functions:int):
    return functions & HWACCEL_FUNCTIONS == functions        

def getActiveHwAccelValues():
    return ACTIVE_HWACCEL_VALUES

loadHardwareAcceleration()

loadedConfig:dict|None = None

def loadConfigFile(path:str):
    global loadedConfig
    if loadedConfig is not None:
        raise Exception("Configuration already loaded!")
    with open(path, 'rb') as configFile:
        tempConfig = tomllib.load(configFile)
        if "main" in tempConfig.keys():
            ffmpegPath = tempConfig['main']['ffmpegPath'] if 'ffmpegPath' in tempConfig['main'] else ""
            if ffmpegPath != "":
                loadHardwareAcceleration(ffmpegPath)
        loadedConfig = configSchema.validate(tempConfig)
        if os.path.samefile(loadedConfig['main']['basepath'], loadedConfig['main']['localBasepath']):
            raise Exception("Values for 'basepath' and 'localBasepath' must be different directories")
        
def getConfig(configPath:str):
    pathParts = configPath.split('.')
    temp = loadedConfig
    for part in pathParts:
        if part == "":
            continue
        temp = temp.get(part)
    return temp

loadConfigFile(configFilePath)

######################



# inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
# inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
# if useHardwareAcceleration&HW_INPUT_SCALE != 0 and cutMode == 'trim':
#    inputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
# HWACCEL_BRAND
