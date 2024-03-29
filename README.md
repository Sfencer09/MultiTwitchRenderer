<!-- #region -->
# MultiTwitchRenderer

This program continuously scans a folder of downloaded Twitch streams from yt-dlp, named in Plex-compliant format, and based on a set of main streamers will generate and run a set of ffmpeg commands to generate a tiled composite video for each main streamer, for each day of streaming. This tiled video will contain all available perspectives of a group stream, with each stream synchronized to within a couple seconds, and will have a separate audio track for each streamer. As other streamers join and leave the main streamer's game session, their perspective will be added or removed.
It aims to be highly configurable, and almost every parameter in the command generation can be tweaked. It also has support for hardware acceleration and adding labels to streams.

Example videos:

https://youtu.be/FvtAdVI1mEc
<iframe width="1903" height="758" src="https://www.youtube.com/embed/n3HS9df2-d4" title="Multiview - 2024/02/08  ChilledChaos" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>

https://youtu.be/UErN2-Qd6P0
<iframe width="1903" height="758" src="https://www.youtube.com/embed/UErN2-Qd6P0" title="Multiview 2023-12-22 ChilledChaos" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>


This source code is best viewed in Jupyter Notebook using the Jupytext extension, though this is not compatible with the urwid library (integration of which is currently in an alpha state)
<!-- #endregion -->
