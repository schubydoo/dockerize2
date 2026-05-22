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
`ghcr.io/schubydoo/dockerize2`. Supported architectures:

- `linux/amd64`
- `linux/arm64`
- `linux/arm/v7` (32-bit hardware-float ABI — Raspberry Pi 32-bit, etc.)

### Image variants

Two flavours are published:

| Tags | Contents | Use for |
|------|----------|---------|
| `:latest`, `:X.Y`, `:X.Y.Z`, `:sha-<short>` | dockerize2 **+ docker CLI + syft + upx** | the full CLI: `--runtime docker`, `--sbom`, `--compress`, `--output-oci`, staging |
| `:slim`, `:X.Y-slim`, `:X.Y.Z-slim`, `:sha-<short>-slim` | dockerize2 only (pure Python) | daemonless `--output-oci` and `-n -o` staging in multi-stage builds; smallest footprint |

`:slim` drops the docker CLI, syft, and upx, so `--runtime docker`, `--sbom`,
and `--compress` are unavailable there — but the fully daemonless paths still
work: `--output-oci PATH` and the `-n -o DIR` staging pattern below.

#### Stage a binary in a multi-stage build (`:slim`)

Use dockerize2 as a build stage to copy a binary and its shared libraries into a
directory, then assemble a `FROM scratch` final image from it:

```dockerfile
FROM ghcr.io/schubydoo/dockerize2:slim AS stage
RUN apt-get update && apt-get install -y --no-install-recommends jq
# -n = no build, -o = output dir: stage jq + its libs into /out
RUN dockerize -n -o /out "$(command -v jq)" \
 && rm -f /out/Dockerfile          # generated build artifact, not part of the image

FROM scratch
COPY --from=stage /out/ /
ENTRYPOINT ["/usr/bin/jq"]
```

dockerize2 resolves **glibc** binaries (it runs on Debian), which suits typical
dynamically-linked Linux executables; it is not the right tool for musl/Alpine
binaries. The `rm -f /out/Dockerfile` matters because `-n -o` writes a generated
`Dockerfile` into the output dir that you don't want copied into the final image.

OCI-archive output — produces a portable OCI image-layout tarball instead of
loading the image into a local store. The difference from classic mode is the
self-contained `.oci.tar` (plus a matching SBOM) that you load yourself.

`--output-oci` is fully daemonless: dockerize assembles the single-layer OCI
image in pure Python — no Docker socket, no `buildx`, no `podman`. Load the
resulting archive with `skopeo`, `oras`, `podman load`, or `docker load` (the
last needs the containerd image store enabled).

```bash
docker run --rm \
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
      --output-oci PATH     Write the image to PATH as an OCI image-layout
                            archive instead of building it through a container
                            engine. Assembled in pure Python — no daemon, no
                            buildx, no socket. Load the archive with skopeo,
                            oras, podman load, or docker load (the last needs
                            the containerd image store).

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

