#!/bin/sh

# xmllint (from libxml2-utils) — validate and reformat XML in a scratch image.
# A good example of a binary with a small, well-defined shared-lib dependency
# set (libxml2 + its transitive deps), all resolved automatically.
#
#   echo '<root><a/></root>' | docker run -i textproc --format -

dockerize -t textproc -e /usr/bin/xmllint /usr/bin/xmllint
