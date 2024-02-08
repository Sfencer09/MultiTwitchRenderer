from datetime import datetime, timezone

def convertToDatetime(timestamp: int | float | str | datetime):
    if isinstance(timestamp, int) or isinstance(timestamp, float):
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
    elif isinstance(timestamp, str):
        dt = datetime.fromisoformat(timestamp)
    elif isinstance(timestamp, datetime):
        dt = timestamp
    else:
        raise TypeError(
            f"Invalid type '{type(timestamp)}' for timestamp '{str(timestamp)}'")
    return dt


def insertSuffix(outpath, suffix):
    dotIndex = outpath.rindex('.')
    return outpath[:dotIndex] + suffix + outpath[dotIndex:]


def extractInputFiles(ffmpegCommand):
    isInput = False
    files = []
    for st in ffmpegCommand:
        if st == '-i':
            isInput = True
        elif isInput:
            if st != 'anullsrc':
                files.append(st)
            isInput = False
    return files

# def localDateFromTimestamp(timestamp:int|float):
#    dt = datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE)
    # startDate = datetime.strftime(startTime, "%Y-%m-%d")
