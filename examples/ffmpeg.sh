#!/bin/sh

# ffmpeg — the canonical "heavy dependency tree" showcase. A single ffmpeg
# binary drags in dozens of codec and container shared libraries; dockerize
# walks them all and packs the closure into a scratch image. This is the
# example that best illustrates why the tool exists.
#
#   docker run --rm ffmpeg -version

dockerize -t ffmpeg -e /usr/bin/ffmpeg /usr/bin/ffmpeg
