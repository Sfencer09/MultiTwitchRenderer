#!/usr/bin/bash

currentGitBranch=$(git symbolic-ref --short HEAD)

echo "$currentGitBranch"

if [ $currentGitBranch = 'master' ]; then

python -O -m PyInstaller ./MultiTwitchRenderer.spec && \
cp dist/MultiTwitchRenderer /mnt/pool2/media/software/ && \
cp dist/config.py /mnt/pool2/media/software/

else

if [ ! -d "/mnt/pool2/media/software/$currentGitBranch/" ]; then
    mkdir "/mnt/pool2/media/software/$currentGitBranch/"
fi

python -O -m PyInstaller ./MultiTwitchRenderer.spec && \
cp dist/MultiTwitchRenderer "/mnt/pool2/media/software/$currentGitBranch/" && \
cp dist/config.py "/mnt/pool2/media/software/$currentGitBranch/"

fi

echo "Build complete!"