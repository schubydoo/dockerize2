#!/bin/sh

# tar plus the common compressors, so the image can handle .tar, .tar.gz,
# .tar.bz2, and .tar.xz archives. GNU tar shells out to gzip/bzip2/xz by
# name (found on the image's default PATH), so all four binaries must be
# packed in.
#
#   docker run --rm -v "$PWD:/data" tar -czf /data/out.tar.gz /data/somefile

dockerize -t tar \
	-e /usr/bin/tar \
	/usr/bin/tar \
	/usr/bin/gzip \
	/usr/bin/bzip2 \
	/usr/bin/xz
