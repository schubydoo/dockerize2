#!/bin/sh

# A statically linked Go binary — the clean contrast to the dynamic examples.
# A CGO_ENABLED=0 build has no .interp section and no shared-library deps, so
# dockerize copies exactly one file: no depsolver work, smallest possible image.
#
# This script compiles a tiny sample binary, then packs it. Requires the Go
# toolchain on the host.
#
#   docker run --rm go-static
#   => hello from a static Go binary

set -e

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/hello.go" <<'GO'
package main

import "fmt"

func main() { fmt.Println("hello from a static Go binary") }
GO

CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o "$tmp/hello" "$tmp/hello.go"

dockerize -t go-static -e /hello -a "$tmp/hello" /hello
