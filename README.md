<!-- #region -->
# MultiTwitchRenderer

This program continuously scans a folder of downloaded Twitch streams, named in Plex-compliant format, and based on a set of main streamers will generate a tiled composite video for each main streamer, for each day of streaming. This tiled video will contain all available perspectives of a group stream, with each stream synchronized as close as possible, and will have a separate audio track for each streamer. As other streamers join and leave the main streamer's game session (or their streams stop and start), their perspective will be added or removed.
It aims to be highly configurable, and almost every parameter in the command generation can be tweaked. It also has support for hardware acceleration and adding labels to streams.

Example videos (videos may not want to embed, just click the links and it should work fine):

https://youtu.be/n3HS9df2-d4
<iframe width="1903" height="758" src="https://www.youtube.com/embed/n3HS9df2-d4" title="Multiview - 2024/02/08  ChilledChaos" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>

https://youtu.be/UErN2-Qd6P0
<iframe width="1903" height="758" src="https://www.youtube.com/embed/UErN2-Qd6P0" title="Multiview 2023-12-22 ChilledChaos" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>


<!-- #endregion -->


<!-- #region -->
## Environment & setup

Coming soon!

## Command-line options

--log-level, --file-log-level : Logging level written to logfile, defaults to 'debug'. Valid values are 'error', 'warning', 'info', 'detail', 'debug', and 'trace'.

--console-log-level : Logging level written to console, defaults to 'warning'. Valid values are 'error', 'warning', 'info', 'detail', 'debug', and 'trace'.

--log-folder : Folder to write log fils to. Defaults to './logs'

--config-file : Path to TOML configuration file. Defaults to './config.toml'


## Configuration

### [main]

basepath : Root folder of downloaded livestreams. Must be filled in before running program.

localBasepath : Scratch folder, used for holding intermediate render files, extracted audio. Must be filled in before running program

outputDirectory : Name of subfolder within basepath that output videos will be placed in. Default: "Rendered Multiviews"

monitorStreamers : List of streamers to automatically queue and run renders for. Must be filled in before running program.

streamersParseChatList : List of streamers who implement a !who and/or !group NightBot command indicating who they are playing with. Default: []

dataFilepath : Path to main data file. Must be writeable. Default: './knownFiles.pickle'

nongroupGames : When not using chats for stream matching, these game titles will be considered solo streams and will not be matched with other streamers based on matching game. Default: ['Just Chatting', "I'm Only Sleeping"]

ffmpegPath : Path to ffmpeg to use, will use $PATH if blank. Default: ''

localTimezone : Time offset of local timezone, days will split at midnight in this timezone. Default: "-06:00" (CST)

statusFilePath : Path to writeable pickle file to hold render statuses. Default: './renderStatuses.pickle'

~~logFolder : DEPRECATED~~

copyFiles : Whether to copy source video files to intermediate local storage before rendering. Default: false

minimumSessionWorkerDelayHours : How many hours old the newest video file must be before attempting to build a render, to account for the time taken to download large VODs. Default: 3

overwriteIntermediateFiles : Whether to always overwrite intermediate files. If false, it will attempt to use existing intermediate files; however, these files may not have been rendered with the same settings as the render in question. Default: true

overwriteOutputFiles : Whether to overwrite existing output files. Default: False

sessionLookbackDays : How many days back from the current date the program should attempt to queue renders for. Does not delete queued renders if this threshold is passed before the render starts or finishes. Default: 14

queueOldestFirst : Whether to queue the oldest (within lookback time) unfinished renders first, rather than the newest first. Default: false


### [main.defaultRenderConfig]

drawLabels : Render streamer names and audio track index at top of streamer's pane. Default: False

startTimeMode : When to start the render at. mainSessionStart means to start the render with the start of the main streamer's stream. 'allSessionStart' means to start at the beginning of the sessions that overlap with the main streamer's first session. Default: "mainSessionStart"

endTimeMode : When to end the render at. 'mainSessionEnd' means to end the render with the end of the main streamer's stream. 'allSessionEnd' means to end with the last of the sessions that overlap with the main streamer's last session. Default: "mainSessionEnd"

sessionTrimLookback : How many seconds after a streamer is marked as leaving the session, that they're actually removed at. Default: 0

sessionTrimLookahead : How many seconds before a streamer is marked as entering the session, that they're actually added at. Default: 0

minGapSize : If a streamer would exit the video for less than this many seconds, try to fill in the gap with available video. Default: 0

outputCodec : Video codec to use to render output video. Default: "libx264"

encodingSpeedPreset : FFMpeg encoding preset to use with output codec. Default: "medium"

useHardwareAcceleration : 4-bit bitmask indicating whether to use hardware acceleration, and for what functions. Will be changed to a more in-depth setting soon. Default: 0

maxHwaccelFiles : Max number of simultaneous files to decode on GPU, or 0 for unlimited. To be removed soon. Default: 0

minimumTimeInVideo : Streamers that appear in the video for fewer than this many seconds will be removed. Default: 900

useChat : Whether to use chats to more accurately determine who is in a session and when. This can make the matching much more accurate, but depends on the streamer (or their mods) keeping the group list up to date. Default: True

preciseAlign : Whether to use audio cross-correlation to more precisely align videos. Will noticeably increase render times, but process is single-threaded and can run separately from render thread. In other words, it has a larger impact on end-to-end latency than total throughput, with the current implementation. Default: false

### [gameAliases]

This section should be a dictionary of arrays. The keys of the dictionary should be the main or official name of the game, and the value should be an array of aliases for that game.

### [streamerAliases]

Similar to gameAliases, this section should be a dictionary of arrays. The keys of the dictionary should be the streamer's name, and the value should be an array of other names that they might appear as in a !who/!group command.

### [internal]

threadCount : Passed to ffmpeg as '-threads' option. Default: 0 (FFmpeg deterrmines the optimal thread count)

#### File extensions, only change if absolutely necessary:

videoExts : Extensions of video files. Default: [ ".mp4", ".mkv" ]

infoExt : Extensions of info JSON files. Default: '.info.json'

chatExt : Extensions of chat files. Default: '.rechat.twitch-gql-20221228.json'

otherExts : Default ['.description', '.jpg']

videoIdRegex : Regex of the video id within the filename. Should be exact enough to avoid false positives. Default: "(v?[\\d]{9,11})"

characterReplacements : Character replacements for filenames done by yt-dlp. Default (may not render properly on all setups): {'?'='？', '/'='⧸', '\'='⧹', ':'='：', '<'='＜', '>'='＞'}

reducedFfmpegMemory : Adds ffmpeg options that attempt to reduce the peak memory usage when rendering, potentially at the cost of a larger output file size. Not recommended. Default: False

~~ENABLE_URWID~~ : Not fully implemented, do not enable outside of development environment. Default: False

outputResolutions : Resolutions of output videos indexed by the maximum number of sub-videos wide the video is. Default: [[], [1920,1080], [3840,1080], [3840,2160], [3840,2160], [3840,2160], [3840,2160], [4480,2520]]

outputBitrates = Bitrates of output videos indexed by the maximum number of sub-videos wide the video is. Default: ["", "6M", "12M", "20M", "25M", "25M", "30M", "40M"]

<!-- #endregion -->