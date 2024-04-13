import json
import subprocess
from typing import Dict

from schema import Schema, Or, And, Optional, Use


from MTRLogging import getLogger
logger = getLogger('RenderConfig')

if __debug__:
    from config import *
exec(open("config.py").read(), globals())


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
    useHardwareAcceleration: int
    maxHwaccelFiles: int
    minimumTimeInVideo: int
    cutMode: str
    useChat: bool
    preciseAlign: bool
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
