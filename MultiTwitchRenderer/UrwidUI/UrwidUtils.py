from typing import Callable


def expandChoices(choices:Callable|list|tuple, *args, **kwargs):
    if callable(choices):
        temp = choices(*args, **kwargs)
        return temp
        #if len(temp) == 0:
        #    return []
    else:
        return tuple(choices)