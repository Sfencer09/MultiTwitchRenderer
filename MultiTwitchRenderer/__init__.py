import sys
import os
if not sys.version_info >= (3, 7, 0):
    raise EnvironmentError(
        "Python version too low, relies on ordered property of dicts")

sys.path.append(os.path.dirname(sys.executable))
#from .MultiTwitchRenderer import generateRenderingCommandMultiSegment