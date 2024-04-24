import os
import argparse
import tomllib

def configFileType(val):
    with open(val, 'rb') as file:
        tomllib.load(file)
        return val

class readableDir(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        prospectiveDir=values
        if not os.path.isdir(prospectiveDir):
            raise argparse.ArgumentError("readable_dir:{0} is not a valid path".format(prospectiveDir))
        if os.access(prospectiveDir, os.R_OK):
            setattr(namespace,self.dest,prospectiveDir)
        else:
            raise argparse.ArgumentError("readable_dir:{0} is not a readable dir".format(prospectiveDir))

class writeableDir(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        prospectiveDir=values
        if not os.path.isdir(prospectiveDir):
            
            raise argparse.ArgumentTypeError("readableDir:{0} is not a valid path".format(prospectiveDir))
        if os.access(prospectiveDir, os.W_OK):
            setattr(namespace, self.dest, prospectiveDir)
        else:
            raise argparse.ArgumentTypeError("readableDir:{0} is not a readable dir".format(prospectiveDir))

argParser = argparse.ArgumentParser()
argParser.add_argument('--log-level', '--file-log-level',
                       choices=('trace', 'debug', 'detail', 'info', 'warning', 'error'),
                       help="Valid values are 'error', 'warning', 'info', 'detail', 'debug', and 'trace'",
                       dest='fileLogLevel',
                       default='debug')
argParser.add_argument('--console-log-level',
                       choices=('trace', 'debug', 'detail', 'info', 'warning', 'error'),
                       help="Valid values are 'error', 'warning', 'info', 'detail', 'debug', and 'trace'",
                       dest='consoleLogLevel',
                       default='warning')
argParser.add_argument('--log-folder',
                       dest='logFolder',
                       #type=writeableDir, # need to modify to allow for new 
                       default='./logs')
argParser.add_argument('--config-file',
                       help='Path to TOML config file',
                       dest='configFilePath',
                       type=configFileType,
                       default='./config.toml')
__args = argParser.parse_args()

def getArgs() -> argparse.Namespace:
    return __args