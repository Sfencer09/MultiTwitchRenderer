import json
import subprocess
from typing import Dict

from schema import Schema, Or, And, Optional, Use


import config

HW_DECODE = 1
HW_INPUT_SCALE = 2
HW_OUTPUT_SCALE = 4
HW_ENCODE = 8


trueStrings = ('t', 'y', 'true', 'yes')


def getHasHardwareAceleration():
    SCALING = HW_INPUT_SCALE | HW_OUTPUT_SCALE
    process1 = subprocess.run(
        [f"{config.ffmpegPath}ffmpeg", "-version"], capture_output=True)
    print(process1.stdout.decode())
    try:
        process2 = subprocess.run(
            ["nvidia-smi", "-q", "-d", "MEMORY,UTILIZATION"], capture_output=True)
        nvidiaSmiOutput = process2.stdout.decode()
        print(nvidiaSmiOutput)
        print(process2.returncode)
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
            print(f"Row count: {rowCount}")
            mask = SCALING
            if decoding:
                mask |= HW_DECODE
            if encoding:
                mask |= HW_ENCODE
            return ('NVIDIA', mask)
    except Exception as ex:
        print(ex)
    try:
        process3 = subprocess.run(["rocm-smi", "--json"], capture_output=True)
        amdSmiOutput = process3.stdout.decode()
        print(amdSmiOutput)
        print(process3.returncode)
        if process3.returncode == 0:
            print("Parsing AMD HW acceleration from rocm-smi not implemented yet, assuming all functions available")
            return ('AMD', HW_DECODE | HW_ENCODE)
    except Exception as ex:
        print(ex)
    return (None, 0)


HWACCEL_BRAND, HWACCEL_FUNCTIONS = getHasHardwareAceleration()
if HWACCEL_BRAND is not None:
    print(f'{HWACCEL_BRAND} hardware video acceleration detected')
    print(f'Functions:')
    if HWACCEL_FUNCTIONS & HW_DECODE != 0:
        print("    Decode")
    if HWACCEL_FUNCTIONS & (HW_INPUT_SCALE | HW_OUTPUT_SCALE) != 0:
        print("    Scaling")
    if HWACCEL_FUNCTIONS & HW_ENCODE != 0:
        print("    Encode")
else:
    print('No hardware video decoding detected!')


# inputOptions.extend(('-threads', '1', '-c:v', 'h264_cuvid'))
# inputOptions.extend(('-threads', '1', '-hwaccel', 'nvdec'))
# if useHardwareAcceleration&HW_INPUT_SCALE != 0 and cutMode == 'trim':
#    inputOptions.extend(('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'))
# HWACCEL_BRAND
HWACCEL_VALUES = {
    'NVIDIA': {
        # 'support_mask': HW_DECODE|HW_INPUT_SCALE|HW_OUTPUT_SCALE|HW_ENCODE,
        'scale_filter': '_npp',
        'pad_filter': '_opencl',
        'upload_filter': '_cuda',
        'decode_input_options': ('-threads', '1', '-c:v', 'h264_cuvid'),
        'scale_input_options': ('-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-extra_hw_frames', '3'),
        'encode_codecs': ('h264_nvenc', 'hevc_nvenc'),
    },
    'AMD': {
        # 'support_mask': HW_DECODE|HW_ENCODE,
        'scale_filter': None,
        'pad_filter': None,
        'upload_filter': '',
        # ('-hwaccel', 'dxva2'), #for AV1 inputs only: ('-extra_hw_frames', '10'),
        'decode_input_options': ('-hwaccel', 'd3d11va'),
        'scale_input_options': None,
        'encode_codecs': ('h264_amf', 'hevc_amf'),
    },
    'Intel': {
        # 'support_mask': HW_DECODE|HW_ENCODE,
        'scale_filter': None,
        'pad_filter': None,
        'upload_filter': '',
        'decode_input_options': ('-hwaccel', 'qsv', '-c:v', 'h264_qsv'),
        'scale_input_options': None,
        'encode_codecs': ('h264_qsv', 'hevc_qsv'),
    },
}
if HWACCEL_BRAND is not None:
    ACTIVE_HWACCEL_VALUES = HWACCEL_VALUES[HWACCEL_BRAND]
else:
    ACTIVE_HWACCEL_VALUES = None


defaultRenderConfig = config.RENDER_CONFIG_DEFAULTS
try:
    with open('./renderConfig.json') as renderConfigJsonFile:
        defaultRenderConfig = json.load(renderConfigJsonFile)
except:
    print("Coult not load renderConfig.json, using defaults from config.py")

acceptedOutputCodecs = ['libx264', 'libx265']
if ACTIVE_HWACCEL_VALUES is not None:
    hardwareOutputCodecs = ACTIVE_HWACCEL_VALUES['encode_codecs']
    acceptedOutputCodecs.extend(hardwareOutputCodecs)
else:
    hardwareOutputCodecs = []

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
    Optional('outputCodec', default=defaultRenderConfig['outputCodec']):
    lambda x: x in acceptedOutputCodecs,
    Optional('encodingSpeedPreset', default=defaultRenderConfig['encodingSpeedPreset']):
    lambda x: x in ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium',
                    'slow', 'slower', 'veryslow') or x in [f'p{i}' for i in range(1, 8)],
    Optional('useHardwareAcceleration', default=defaultRenderConfig['useHardwareAcceleration']):
    And(Use(int), lambda x: x & HWACCEL_FUNCTIONS == x),
    # And(Use(int), lambda x: 0 <= x < 16), #bitmask; 0=None, bit 1(1)=decode, bit 2(2)=scale input, bit 3(4)=scale output, bit 4(8)=encode
    Optional('maxHwaccelFiles', default=defaultRenderConfig['maxHwaccelFiles']):
    And(Use(int), lambda x: x >= 0),
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
    useHardwareAcceleration: int
    maxHwaccelFiles: int
    minimumTimeInVideo: int
    cutMode: str
    useChat: bool
    includeStreamers: None | Dict[str, None | Dict[str, None | str]]
    excludeStreamers: None | Dict[str, None | Dict[str, None | str]]

    def __init__(self, **kwargs):
        values:dict = renderConfigSchema.validate(kwargs)
        if values['outputCodec'] in hardwareOutputCodecs:
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
            if values['outputCodec'] not in hardwareOutputCodecs:
                raise Exception(
                    f"Must specify hardware-accelerated output codec if hardware encoding bit in useHardwareAcceleration is enabled")
        for key, value in values.items():
            setattr(self, key, value)

    def copy(self):
        return RenderConfig(**self.__dict__)

    def __repr__(self):
        return f"RenderConfig({', '.join(('='.join((key, str(value))) for key, value in self.__dict__.items()))})"
