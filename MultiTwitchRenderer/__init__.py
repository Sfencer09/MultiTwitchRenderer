import sys
if not sys.version_info >= (3, 7, 0):
    raise EnvironmentError(
        "Python version too low, relies on ordered property of dicts")

#from MultiTwitchRenderer import generateRenderingCommandMultiSegment