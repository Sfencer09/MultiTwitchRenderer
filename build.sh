#!/usr/bin/bash

python -O -m PyInstaller ./MultiTwitchRenderer.spec && \
cp dist/MultiTwitchRenderer /mnt/pool2/media/software/ && cp dist/config.py /mnt/pool2/media/software/