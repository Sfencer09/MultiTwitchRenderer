from typing import Dict, List, Set

from SourceFile import SourceFile
from Session import Session

# Shared state

print('Creating data structures')
allFilesByVideoId: Dict[str, 'SourceFile'] = {}  # string:SourceFile
allFilesByStreamer: Dict[str, 'SourceFile'] = {}  # string:[SourceFile]
allStreamersWithVideos: List[str] = []
allStreamerSessions: Dict[str, List['Session']] = {}
allScannedFiles: Set[str] = set()
filesBySourceVideoPath: Dict[str, 'SourceFile'] = {}