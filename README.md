# dockerize2

> **About this fork.** `dockerize2` continues
> [larsks/dockerize](https://github.com/larsks/dockerize) — picking up
> where upstream paused in 2020 to refresh the toolchain (PEP 621
> packaging, type hints, uv, Python 3.11+) and add new capabilities:
> UPX compression, OCI-archive output, SBOM generation, a `doctor`
> health check, and a multi-arch container image. Original copyright
> is preserved (see [NOTICE](NOTICE) and [LICENSE.txt](LICENSE.txt));
> the project remains GPL-3.0-licensed.

`dockerize2` packs up your dynamically linked ELF binaries and all their
dependencies and turns them into a minimal `FROM scratch` Docker image —
optionally UPX-compressed, with a generated SBOM, emitted as either a
daemon push or an OCI archive.

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

OCI-archive output — produces a portable OCI tarball instead of loading the
image into a local store. `docker buildx` still talks to the Docker daemon,
so the socket is mounted here too; the difference from classic mode is the
self-contained `.oci.tar` (plus a matching SBOM) that you load yourself. A
fully daemonless build is only possible with `--runtime podman`, which is
not bundled in this image — you would supply podman yourself.

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/work \
  -v /usr/sbin/mini_httpd:/usr/sbin/mini_httpd:ro \
  ghcr.io/schubydoo/dockerize2:latest \
    -t httpd \
    --output-oci /work/httpd.oci.tar \
    --sbom /work/httpd.sbom.spdx.json \
    --compress \
    /usr/sbin/mini_httpd
```

Then on the host:

```bash
docker load -i httpd.oci.tar
```

Classic mode — build straight into the daemon's local image store:

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/sbin/mini_httpd:/usr/sbin/mini_httpd:ro \
  ghcr.io/schubydoo/dockerize2:latest \
    -t httpd /usr/sbin/mini_httpd
```

Run the health check:

```bash
docker run --rm ghcr.io/schubydoo/dockerize2:latest doctor
```

## Synopsis

    usage: dockerize [-h] [--tag TAG] [--cmd CMD] [--entrypoint ENTRYPOINT]
                     [--no-build] [--output-dir OUTPUT_DIR] [--add-file SRC DST]
                     [--symlinks SYMLINKS] [--user USER] [--group GROUP]
                     [--filetools] [--no-host-lookup] [--allow-sensitive]
                     [--nss-modules NSS_MODULES] [--label KEY=VALUE] [--compress]
                     [--compress-level {normal,best,ultra}] [--compress-libs]
                     [--sbom PATH]
                     [--sbom-format {spdx-json,cyclonedx-json,syft-json}]
                     [--output-oci PATH] [--runtime RUNTIME] [--buildcmd BUILDCMD]
                     [--verbose] [--debug] [--version]
                     ...

    positional arguments:
      paths

    options:
      -h, --help            show this help message and exit
      --add-file, -a SRC DST
                            Add file <src> to image at <dst>
      --symlinks, -L SYMLINKS
                            One of preserve, copy-unsafe, skip-unsafe, copy-all
      --user, -u USER       Add user to /etc/passwd in image
      --group, -g GROUP     Add group to /etc/group in image
      --filetools           Add common file manipulation tools
      --runtime, -R RUNTIME
                            Set container engine for building
      --buildcmd, -B BUILDCMD
                            Set command for building
      --version             show program's version number and exit

    Docker options:
      --tag, -t TAG         Tag to apply to Docker image
      --cmd, -c CMD
      --entrypoint, -e ENTRYPOINT

    Output options:
      --no-build, -n        Do not build Docker image
      --output-dir, -o OUTPUT_DIR

    Security options:
      --no-host-lookup      Reject bare user/group names; require colon-delimited
                            entries.
      --allow-sensitive     Allow copying known-sensitive host paths (/etc/shadow,
                            ~/.ssh/*, etc.).
      --nss-modules NSS_MODULES
                            Comma-separated list of nss modules to copy into the
                            image (default: files,dns). Limits CVE surface vs.
                            copying every libnss*.
      --label KEY=VALUE     Add an OCI image label. Repeatable.

    Compression options:
      --compress            Apply UPX compression to ELF executables in the image.
      --compress-level {normal,best,ultra}
                            UPX level when --compress is set (default: best).
      --compress-libs       Also compress shared libraries (deprecated UPX
                            feature; increases incompatibility risk — use at your
                            own risk).

    Output options (advanced):
      --sbom PATH           Write an SBOM of the build context to PATH (requires
                            syft).
      --sbom-format {spdx-json,cyclonedx-json,syft-json}
                            SBOM format (default: spdx-json).
      --output-oci PATH     Emit an OCI image archive to PATH instead of pushing
                            into a daemon. Uses `docker buildx` if available;
                            falls back to `podman save --format oci-archive`.
                            Removes the need for /var/run/docker.sock when running
                            dockerize from a container.

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

Stage some default content, then create an image named `httpd`:

    mkdir -p /tmp/www && echo '<h1>dockerize2</h1>' > /tmp/www/index.html

    dockerize -t httpd \
      -a /tmp/www /var/www \
      --entrypoint '/usr/sbin/mini_httpd -D -d /var/www -p 80' \
      /usr/sbin/mini_httpd

Serve the baked-in content:

    docker run --rm -p 8080:80 httpd

Serve your own content instead:

    docker run --rm -p 8080:80 -v /my/content:/var/www httpd

## Acknowledgements

See [`NOTICE`](NOTICE) for credit to the original
[`dockerize`](https://github.com/larsks/dockerize) project and Lars
Kellogg-Stedman, on whose work this fork builds.

Development of `dockerize2` is assisted by Claude (Anthropic), used as a
pair-programming and code-review tool. The maintainer directs all work,
reviews each pull request, and retains editorial control over what is
merged.

