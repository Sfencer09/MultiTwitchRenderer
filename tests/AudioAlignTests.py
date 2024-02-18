import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# sys.path.insert(0, os.path.abspath(os.path.join(sys.executable)))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "MultiTwitchRenderer")
    ),
)
from AudioAlignment import findAudioOffset, findAverageAudioOffset, findFileOffset


# file1 = "ChilledChaos/S1/ChilledChaos - 2024-02-15 - IT'S A HARD KNOCK LIFE...FOR US! (The Game of Life 2) ｜ Worms and Intruder After! v2063753759"
file1 = "ChilledChaos/S1/ChilledChaos - 2024-02-06 - TOWN OF SALEM 2 RETURNS! ｜ Among Us After! v2055212961"
# file2 = "LarryFishburger/S1/LarryFishburger - 2024-02-15 - Showing my Worm to my Friends - !Sponsors !Socials v2063760958"
# file2 = "LarryFishburger/S1/LarryFishburger - 2024-02-06 - Town of Salem 2 w. Friends ：) - !Sponsors !Socials v2055216281"
file2 = "ZeRoyalViking/S1/ZeRoyalViking - 2024-02-06 - TOWN OF SALEM 2 RETURNS w⧸ Friends (Among Us after!) v2055210338"

print(
    #findAudioOffset(
    findAverageAudioOffset(
        f"/mnt/pool2/media/Twitch Downloads/{file1}.mp4",
        f"/mnt/pool2/media/Twitch Downloads/{file2}.mp4",
        # duration=5400,
        #window=3600,
        # start=10800,
    )
)
