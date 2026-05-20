# dockerize2

> **Fork notice.** `dockerize2` is the successor to
> [larsks/dockerize](https://github.com/larsks/dockerize), which has been
> dormant since 2020. This repository is where active development now
> happens. Original copyright is preserved (see [NOTICE](NOTICE) and
> [LICENSE.txt](LICENSE.txt)); the project remains GPL-3.0-licensed.

`dockerize2` packs up your dynamically linked ELF binaries and all their
dependencies and turns them into a minimal `FROM scratch` Docker image.

Some example images built with the original tool are available from:

- <https://hub.docker.com/u/dockerizeme/>

## Installation

`dockerize2` is a standard Python package. Until v0.3.0 lands on PyPI you
can install it from this repository:

    pip install git+https://github.com/schubydoo/dockerize2

The installed console script is still called `dockerize` so existing
scripts continue to work unchanged.

## Run from a container

A pre-built multi-arch image is available at
`ghcr.io/schubydoo/dockerize2`. Tags follow `:latest`, `:0.3`, `:0.3.0`,
`:sha-<short>`. Supported architectures:

- `linux/amd64`
- `linux/arm64`
- `linux/arm/v7` (32-bit hardware-float ABI — Raspberry Pi 32-bit, etc.)

Recommended invocation — emit an OCI archive so you don't need to mount
the Docker socket:

```bash
docker run --rm \
  -v "$PWD":/work \
  -v /usr/sbin/thttpd:/usr/sbin/thttpd:ro \
  ghcr.io/schubydoo/dockerize2:latest \
    -t thttpd \
    --output-oci /work/thttpd.oci.tar \
    --sbom /work/thttpd.sbom.spdx.json \
    --compress \
    /usr/sbin/thttpd
```

Then on the host:

```bash
docker load -i thttpd.oci.tar
```

Classic mode (mounts the daemon socket — less ideal but supported):

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/sbin/thttpd:/usr/sbin/thttpd:ro \
  ghcr.io/schubydoo/dockerize2:latest \
    -t thttpd /usr/sbin/thttpd
```

Run the health check:

```bash
docker run --rm ghcr.io/schubydoo/dockerize2:latest doctor
```

## Synopsis

    usage: dockerize [-h] [--tag TAG] [--cmd CMD] [--entrypoint ENTRYPOINT]
                     [--no-build] [--output-dir OUTPUT_DIR] [--add-file SRC DST]
                     [--symlinks SYMLINKS] [--user USER] [--group GROUP]
                     [--filetools] [--verbose] [--debug] [--version]
                     ...

    positional arguments:
      paths

    optional arguments:
      -h, --help            show this help message and exit
      --add-file SRC DST, -a SRC DST
                            Add file <src> to image at <dst>
      --symlinks SYMLINKS, -L SYMLINKS
                            One of preserve, copy-unsafe, skip-unsafe, copy-all
      --user USER, -u USER  Add user to /etc/passwd in image
      --group GROUP, -g GROUP
                            Add group to /etc/group in image
      --filetools           Add common file manipulation tools
      --version             show program's version number and exit

    Docker options:
      --tag TAG, -t TAG     Tag to apply to Docker image
      --cmd CMD, -c CMD
      --entrypoint ENTRYPOINT, -e ENTRYPOINT

    Output options:
      --no-build, -n        Do not build Docker image
      --output-dir OUTPUT_DIR, -o OUTPUT_DIR

    Logging options:
      --verbose
      --debug

## A simple example

Create a `sed` image:

    dockerize -t sed /bin/sed

Use it:

    $ echo hello world | docker run -i sed s/world/jupiter
    hello jupiter

## A more complicated example

Create an image named `thttpd`:

    dockerize -t thttpd \
      -a /var/www/thttpd /var/www \
      --entrypoint '/usr/sbin/thttpd -D' \
      --cmd '-d /var/www' \
      /usr/sbin/thttpd

Serve default content:

    docker run thttpd

Serve your own content:

    docker run -v /my/content:/var/www thttpd

