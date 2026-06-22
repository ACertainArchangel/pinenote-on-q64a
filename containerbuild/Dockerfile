# PineNote OS build environment — aarch64 Arch Linux (for makepkg + mkosi).
#
# Build tooling for this project (hrdl's PineNote tree, retargeted to the
# Quartz64-A). It is NOT part of hrdl's source: it exists so the build runs on a
# non-Arch host. Most packages come prebuilt from hrdl's binary repo; the ONLY
# thing built from source here is the kernel (it must ship the rk3566-quartz64-a
# DTB) and U-Boot — so this image carries the kernel toolchain + U-Boot/binman
# deps + the SD-imaging tools, plus mkosi.
#
# On an aarch64 host this container runs natively, so the kernel compiles at full
# speed (no qemu — host arch == target arch). Built + driven by build-and-flash.sh.
ARG BUILD_IMAGE=menci/archlinuxarm:latest
FROM ${BUILD_IMAGE}

# Docker bind-mounts /etc/resolv.conf and /etc/hosts read-only, and the container
# may lack landlock — patch pacman.conf so the upgrade still commits: don't
# extract those files, and skip pacman's sandbox. Also disable CheckSpace:
# pacman's pre-extraction disk-space check misbehaves in a container (flags the
# read-only bind mounts and miscalculates free space, aborting with a bogus
# "not enough free disk space"). NoExtract/DisableSandbox don't cover this.
RUN printf 'NoExtract = etc/resolv.conf etc/hosts\nDisableSandbox\n' > /tmp/pacopt \
 && sed -i '/^\[options\]/r /tmp/pacopt' /etc/pacman.conf && rm -f /tmp/pacopt \
 && sed -i 's/^CheckSpace/#CheckSpace/' /etc/pacman.conf

# Feed entropy with haveged FIRST — otherwise `pacman-key --init` can block for
# many minutes on a low-entropy container host. Then refresh the (often stale)
# Arch Linux ARM keyring.
RUN pacman -Syu --noconfirm --needed haveged \
 && haveged -w 1024 \
 && pacman-key --init \
 && (pacman-key --populate archlinuxarm 2>/dev/null || true)

# Build deps. IMPORTANT: keep this its OWN step with no `|| true` — chaining a
# failing dep install as `(...) && pacman -S <deps> ... || true` parses as
# `(...) || true` and silently bakes an image MISSING base-devel/clang/sudo.
#  - base-devel git sudo: makepkg (non-root) + the imaging step's sudo.
#  - clang llvm lld bc: the kernel toolchain (pinenote_defconfig builds with LLVM).
#  - gptfdisk e2fsprogs dosfstools parted zstd: SD-imaging (sgdisk/mkfs.ext4/
#    partprobe) + tar.zst handling.
#  - bison flex swig python-setuptools python-pyelftools openssl dtc: U-Boot +
#    binman/pylibfdt build deps.
#  - python-pip python-pefile: mkosi (installed via pip below); v26 inspects the
#    aarch64 kernel Image as a PE/EFI binary for Split Artifacts and needs pefile.
RUN pacman -S --noconfirm --needed \
      base-devel git sudo \
      clang llvm lld bc \
      gptfdisk e2fsprogs dosfstools parted zstd \
      bison flex swig python-setuptools python-pyelftools openssl dtc \
      python-pip python-pefile \
 && pacman -Scc --noconfirm >/dev/null 2>&1 || true

# mkosi: install a pinned upstream release via pip+git, NOT the Arch package.
#  1. Arch Linux ARM ships an ancient mkosi that can't parse this repo's config.
#  2. `pip install mkosi` no longer works — mkosi stopped publishing to PyPI.
# Pinned to v26 (verified to parse mkosi.conf); bump deliberately.
RUN pip install --break-system-packages "git+https://github.com/systemd/mkosi.git@v26"

WORKDIR /work
# The non-root build user is created at runtime (entrypoint.sh) to match your
# host uid/gid, so files written on the bind mount stay owned by you.
ENTRYPOINT ["/bin/bash", "/work/containerbuild/entrypoint.sh"]
