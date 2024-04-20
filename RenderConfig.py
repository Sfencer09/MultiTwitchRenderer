from io import BytesIO
import json
import sys
import os
import subprocess
from typing import Dict, Iterable, List, Tuple

from schema import Schema, Or, And, Optional, Use


from MTRLogging import getLogger
logger = getLogger('RenderConfig')

from MTRConfig import isDevicePath, testHardwareFunctions, getHardwareAccelerationDevicesV2, trueStrings, getConfig, isAcceptedOutputCodec, isHardwareOutputCodec, HW_DECODE, HW_ENCODE, HW_INPUT_SCALE, HW_OUTPUT_SCALE, HWACCEL_VALUES, hardwareAccelDeviceSchema

defaultRenderConfig = getConfig('main.defaultRenderConfig')

""" def getHasHardwareAceleration():
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


HWACCEL_BRAND, HWACCEL_FUNCTIONS = getHasHardwareAceleration()

def getAllHardwareAccelerationFunctions() -> Dict[str, int]:
    SCALING = HW_INPUT_SCALE | HW_OUTPUT_SCALE
    #ffmpegVersionProcess = subprocess.run(
    #    [f"{ffmpegPath}ffmpeg", "-version"], capture_output=True)
    #ffmpegInfo = ffmpegVersionProcess.stdout.decode()
    ffmpegInfo = subprocess.check_output([f"{ffmpegPath}ffmpeg", "-version"], universal_newlines=True, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    ffmpegBuildInfo = [row for row in ffmpegInfo.split('\n') if row.startswith("configuration:")][0]
    ffmpegBuildOptions = [elem for elem in ffmpegBuildInfo.split(' ') if elem.startswith('-')]
    logger.detail(ffmpegInfo)
    ffmpegCodecs = subprocess.check_output([f"{ffmpegPath}ffmpeg", "-version"], universal_newlines=True, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    functionsSupported = {}
    # NVIDIA
    try:
        nvidiaSmiProcess = subprocess.run(
            ["nvidia-smi", "-q", "-d", "MEMORY,UTILIZATION"], capture_output=True)
        nvidiaSmiOutput = nvidiaSmiProcess.stdout.decode()
        logger.info(nvidiaSmiOutput)
        logger.info(nvidiaSmiProcess.returncode)
        if nvidiaSmiProcess.returncode == 0:
            encoding = False
            decoding = False
            rowCount = 0
            for row in nvidiaSmiOutput.split('\n'):
                if 'Encoder' in row:
                    if 'N/A' not in row:
                        logger.info("Driver reported encoding capabilities")
                        if "--enable-nvenc" in ffmpegBuildOptions:
                            encoding = True
                            logger.info("FFMpeg build info includes --enable-nvenc, NVIDIA hardware encoding enabled")
                        else:
                            logger.warning("FFMpeg build does not include --enable-nvenc despite driver reporting encoding support, make sure a suitable ffmpeg process is specified in config.py")
                elif 'Decoder' in row:
                    if 'N/A' not in row:
                        logger.info("Driver reported decoding capabilities")
                        if "--enable-nvdec" in ffmpegBuildOptions:
                            decoding = True
                            logger.info("FFMpeg build info includes --enable-nvdec, NVIDIA hardware decoding enabled")
                        else:
                            logger.warning("FFMpeg build does not include --enable-nvdec despite driver reporting decoding support, make sure a suitable ffmpeg process is specified in config.py")
                rowCount += 1
            logger.info(f"Row count: {rowCount}")
            mask = SCALING
            if decoding:
                mask |= HW_DECODE
            if encoding:
                mask |= HW_ENCODE
            # return ('NVIDIA', mask)
            functionsSupported["NVIDIA"] = mask
    except Exception as ex:
        logger.debug(ex)
    # AMD
    try:
        amdSmiProcess = subprocess.run(["rocm-smi", "--json"], capture_output=True)
        amdSmiOutput = amdSmiProcess.stdout.decode()
        logger.info(amdSmiOutput)
        logger.info(amdSmiProcess.returncode)
        if amdSmiProcess.returncode == 0:
            logger.info("Parsing AMD HW acceleration from rocm-smi not implemented yet, assuming all functions available")
            return ('AMD', HW_DECODE | HW_ENCODE)
    except Exception as ex:
        logger.debug(ex)
        pass
    # Intel
    return functionsSupported  """

def _generateTestVideo() -> bytes:
    fullFfmpegPath = getConfig("main.ffmpegPath") + "ffmpeg"
    testVideoBuildCommand = [fullFfmpegPath, 
                             "-hide_banner", "-nostats",
                             "-f", "lavfi",
                             "-i", "testsrc=size=1280x720",
                             "-t", "1",
                             "-pix_fmt", "yuv420p",
                             "-f", "matroska",
                             "pipe:"]
    testVideoData = subprocess.check_output(testVideoBuildCommand,
                                            stdin=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,
                                            text=False)
    return testVideoData

def _testHardwareFunctions(deviceName:str|int, testVideoData:None|bytes=None) -> tuple:
    if testVideoData is None:
        testVideoData = _generateTestVideo()
    fullFfmpegPath = getConfig("main.ffmpegPath") + "ffmpeg"
    commandStart = [fullFfmpegPath, '-hwaccel_device', str(deviceName)]
    def _testCommand(command):
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        proc.communicate(testVideoData)
        return proc.wait() == 0
    functionMask = 0
    for hwbrand, values in HWACCEL_VALUES.items():
        decodingTestCommand = commandStart + \
                            list(values['decode_input_options']) + \
                                ['-f', 'matroska', '-i', 'pipe:',
                                '-f', 'null', '-']

        if _testCommand(decodingTestCommand):
            functionMask |= HW_DECODE
            logger.detail(f"Found decode function from brand {hwbrand} on device {deviceName}")
        else:
            continue # if there's no decode acceleration, there's probably just no video hardware for this brand
        
        scalingTestCommand = commandStart + list(values['decode_input_options']) + \
            list(values['scale_input_options']) + ['-f', 'matroska', '-i', 'pipe:', \
                'vf', f'scale{values["scale_filter"]}=-1:480:force_original_aspect_ratio=decrease:format=yuv420p:', '-f', 'null', '-']
        if _testCommand(scalingTestCommand):
            functionMask |= HW_INPUT_SCALE | HW_OUTPUT_SCALE
            logger.detail(f"Found decode function from brand {hwbrand} on device {deviceName}")
        
        encodingTestCommand = commandStart + ['-f', 'matroska', '-i', 'pipe:', '-c:v', values['encode_codecs'][0], '-f', 'null', '-']
        if _testCommand(encodingTestCommand):
            functionMask |= HW_ENCODE
            logger.detail(f"Found decode function from brand {hwbrand} on device {deviceName}")
        
        return (hwbrand, functionMask)
    return None

"""Got tired of trying to figure out ways of scanning the video hardware available,
and figured the most accurate way to check for hardware acceleration features is 
simply to try and use them and see if that succeeds. The trick is to do it without
packing a test video, or in fact writing anything to disk."""
def getHardwareAccelerationDevicesV2() -> Dict[str, Tuple[str, int]]:
    testVideoData = _generateTestVideo()
    deviceIndex = 0
    hwDeviceFunctions:Dict[Tuple[str, int]] = {}
    functionMask = ...
    while functionMask is not None:
        functionMask = _testHardwareFunctions(deviceName=deviceIndex, testVideoData=testVideoData)
        if functionMask is not None:
            hwDeviceFunctions[str(deviceIndex)] = functionMask
        deviceIndex += 1
    return hwDeviceFunctions

HW_ACCEL_DEVICES = getHardwareAccelerationDevicesV2()

""" 
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
 """

# inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
# inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
# if useHardwareAcceleration&HW_INPUT_SCALE != 0 and cutMode == 'trim':
#    inputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
# HWACCEL_BRAND

#if HWACCEL_BRAND is not None:
#ACTIVE_HWACCEL_VALUES = HWACCEL_VALUES[HWACCEL_BRAND]
#else:
#    ACTIVE_HWACCEL_VALUES = None


#defaultRenderConfig = RENDER_CONFIG_DEFAULTS
# try:
#     with open('./renderConfig.json') as renderConfigJsonFile:
#         defaultRenderConfig = json.load(renderConfigJsonFile)
# except:
#     print("Coult not load renderConfig.json, using defaults from config.py")

acceptedOutputCodecs = set(['libx264', 'libx265'])
hardwareOutputCodecs = set()
#for brand, function in HW_ACCEL_DEVICES:
for device, info in HW_ACCEL_DEVICES.items():
    brand, device = info
    if function & HW_ENCODE:
        codecs = HWACCEL_VALUES[brand].encode_codecs
        hardwareOutputCodecs.update(codecs)

class VideoAccelDevice:
    def __init__(self, devicePath:str, brand:str, functions:int, priority:int, maxDecodeDevices:int):
        self.devicePath = devicePath
        self.brand = brand
        self.functions = functions
        self.priority = priority
        self.maxDecodeDevices = maxDecodeDevices
        
def buildHardwareAccelList(settings:Dict[str, Dict[str, str|int]]) -> List[dict]:
    """Returns a sorted list of devices that can be used for hardware acceleration,
        sorted by priority and capabilities.
        
        Intended to be the transformer for the useHardwareAcceleration setting

    Args:
        settings (Dict[str, Dict[str, str|int]]): A dictionary where each key is a device identifier,
        either a number or a device path. Each value is a dictionary with key 'mask' (int),
        and optionally 'maxDecodeStreams' (int > 0) and/or 'priority' (int, lower value = used first if possible,
        default=last place)
    """
    if settings is None:
        return []
    __default_priority = 100000000000000000000
    __default_decode_streams = 0
    permittedDevices = []
    
    for device, info in settings.items():
        if device not in HW_ACCEL_DEVICES.keys():
            try:
                int(device)
            except:
                if not _isDevicePath(device):
                    logger.error(f"{device} is not an accessible device path!")
                    #raise ValueError(f"{device} is not accessible!")
                    continue
            HW_ACCEL_DEVICES[device] = _testHardwareFunctions(device)
        deviceBrand, functionMask = HW_ACCEL_DEVICES[device]
        permittedMask = info['mask']
        if 'maxDecodeStreams' in info:
            maxDecodeStreams = int(info['maxDecodeStrings'])
        else:
            maxDecodeStreams = __default_decode_streams
        if 'priority' in info:
            priority = info['priority']
        else:
            priority = __default_priority
        finalMask = permittedMask & functionMask
        if finalMask & (HW_ENCODE | HW_DECODE) != 0:
            permittedDevices.append({'devicePath': device, 'brand':deviceBrand, 'functions':finalMask, 'priority':priority, 'maxDecodeStreams':maxDecodeStreams})
    
    permittedDevices.sort(key=lambda x: (x['priority'], -x['maxDecodeStreams'], -x['functions']))
    
    for entry in permittedDevices:
        if entry['priority'] == __default_priority:
            del entry['priority']
        if entry['maxDecodeStreams'] == __default_decode_streams:
            del entry['maxDecodeStreams']
    
    return permittedDevices
        

renderConfigSchema = Schema({
    Optional('drawLabels', default=defaultRenderConfig['drawLabels']):
        Or(bool, Use(lambda x: x.lower() in trueStrings)),
    Optional('startTimeMode', default=defaultRenderConfig['startTimeMode']):
        lambda x: x in ('mainSessionStart', 'allOverlapStart'),
    Optional('endTimeMode', default=defaultRenderConfig['endTimeMode']):
        lambda x: x in ('mainSessionEnd', 'allOverlapEnd'),
    Optional('logLevel', default=defaultRenderConfig['logLevel']):
        And(Use(int), lambda x: 0 <= x <= 4),  # max logLevel = 4
    Optional('sessionTrimLookback', default=defaultRenderConfig['sessionTrimLookback']):
        # TODO: convert from number of segments to number of seconds. Same for lookahead
        Use(int),
    Optional('sessionTrimLookahead', default=defaultRenderConfig['sessionTrimLookahead']):
        And(Use(int), lambda x: x >= 0),
    Optional('sessionTrimLookbackSeconds', default=defaultRenderConfig['sessionTrimLookbackSeconds']):
        And(Use(int), lambda x: x >= 0),  # Not implemented yet
    Optional('sessionTrimLookaheadSeconds', default=defaultRenderConfig['sessionTrimLookaheadSeconds']):
        And(Use(int), lambda x: x >= 0),
    # Optional(Or(Optional('sessionTrimLookback', default=0),
    # Optional('sessionTrimLookbackSeconds', default=0), only_one=True), ''): And(int, lambda x: x>=-1),
    # Optional(Or(Optional('sessionTrimLookahead', default=0),
    # Optional('sessionTrimLookaheadSeconds', default=600), only_one=True): And(int, lambda x: x>=0),
    Optional('minGapSize', default=defaultRenderConfig['minGapSize']):
        And(Use(int), lambda x: x >= 0),
    Optional('outputCodec', default=defaultRenderConfig['outputCodec']): #needs additional validation in constructor
        lambda x: any((x in brandInfo['encode_codec_options'].keys()
                      for brandInfo in HWACCEL_VALUES.values())),
    Optional('encodingSpeedPreset', default=defaultRenderConfig['encodingSpeedPreset']): #needs additional validation in constructor
        #lambda x: x in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium',
        #            'slow', 'slower', 'veryslow') or x in [f'p{i}' for i in range(1, 8)],
        lambda x: any((any((x in codecOptions['validPresets'] for codecOptions in brandInfo['encode_codec_options']))
                      for brandInfo in HWACCEL_VALUES.values())),
    Optional('hardwareAccelDevices', default=defaultRenderConfig['hardwareAccelDevices']):
    #And(Use(int), lambda x: x & HWACCEL_FUNCTIONS == x),
    And(Or({},
           hardwareAccelDeviceSchema, 
           {Or(And(Use(int), lambda x: x>=0, Use(str)),
               And(str, _isDevicePath)):
                   hardwareAccelDeviceSchema}),
        Use(buildHardwareAccelList)),
    # And(Use(int), lambda x: 0 <= x < 16), #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale input, bit 3(4)=scale output, bit 4(8)=encode
    #Optional('maxHwaccelFiles', default=defaultRenderConfig['maxHwaccelFiles']):
    #And(Use(int), lambda x: x >= 0),
    Optional('minimumTimeInVideo', default=defaultRenderConfig['minimumTimeInVideo']):
        And(Use(int), lambda x: x >= 0),
    Optional('cutMode', default=defaultRenderConfig['cutMode']):
        lambda x: x in ('chunked', ),  # 'trim', 'segment'),
    Optional('useChat', default=defaultRenderConfig['useChat']):
        Or(bool, Use(lambda x: x.lower() in trueStrings)),
    # overrides chat, but will not prevent game matching
    Optional('includeStreamers', default=None):
        # Cannot be passed as string
        Or(lambda x: x is None, [str], {str: Or(lambda x: x is None, [str])}),
    Optional('excludeStreamers', default=None):
        # Cannot be passed as string
        Or(lambda x: x is None, [str], {str: Or(lambda x: x is None, [str])}),
    Optional('preciseAlign', default=defaultRenderConfig['preciseAlign']):
        Or(bool, Use(lambda x: x.lower() in trueStrings)),
})


class RenderConfig:
    drawLabels: bool
    startTimeMode: str
    endTimeMode: str
    logLevel: int
    sessionTrimLookback: int
    sessionTrimLookahead: int
    sessionTrimLookbackSeconds: int
    sessionTrimLookaheadSeconds: int
    minGapSize: int
    outputCodec: str
    encodingSpeedPreset: str
    hardwareAccelerationDevices: List[Dict[str, str|int]]
    #maxHwaccelFiles: int
    minimumTimeInVideo: int
    cutMode: str
    useChat: bool
    preciseAlign: bool
    includeStreamers: None | Dict[str, None | Dict[str, None | str]]
    excludeStreamers: None | Dict[str, None | Dict[str, None | str]]

    def __init__(self, **kwargs):
        values:dict = renderConfigSchema.validate(kwargs)
        if isHardwareOutputCodec(values['outputCodec']):
            if values['useHardwareAcceleration'] & HW_ENCODE == 0:
                raise Exception(
                    f"Must enable hardware encoding bit in useHardwareAcceleration if using hardware-accelerated output codec {values['outputCodec']}")
            if values['encodingSpeedPreset'] not in [f'p{i}' for i in range(1, 8)]:
                raise Exception("Must use p1-p7 presets with hardware codecs")
        elif values['encodingSpeedPreset'] not in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'):
            raise Exception("Can only use p1-p7 presets with hardware codecs")
        if values['useHardwareAcceleration'] & HW_OUTPUT_SCALE != 0:
            if values['useHardwareAcceleration'] & HW_ENCODE == 0:
                raise Exception(
                    f"Hardware-accelerated output scaling must currently be used with hardware encoding")
        if values['useHardwareAcceleration'] & HW_ENCODE != 0:
            if not isHardwareOutputCodec(values['outputCodec']):# not in hardwareOutputCodecs:
                raise Exception(
                    f"Must specify hardware-accelerated output codec if hardware encoding bit in useHardwareAcceleration is enabled")
        for key, value in values.items():
            setattr(self, key, value)

    def copy(self):
        return RenderConfig(**self.__dict__)

    def __repr__(self):
        return f"RenderConfig({', '.join(('='.join((key, str(value))) for key, value in self.__dict__.items()))})"
