#!/bin/sh

# jq — the simplest possible dockerize target: a single executable with a
# handful of shared-lib deps (libjq, libonig, libc), no extra files. When
# exactly one binary is given and no --entrypoint is set, dockerize uses that
# binary as the image entrypoint automatically.
#
#   echo '{"hello":"world"}' | docker run -i jq .hello
#   => "world"

dockerize -t jq /usr/bin/jq
