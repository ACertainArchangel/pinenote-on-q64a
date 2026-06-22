#!/usr/bin/env bash
# build-and-flash.sh — PineNote OS for the Quartz64-A + 10.3" e-ink.
#
#   local kernel pkg (with rk3566-quartz64-a DTB)  ->  mkosi rootfs tar
#   ->  bootable SD image (U-Boot + ext4 root)     ->  optional dd flash
#
# Only the kernel is built from source (it must ship the Quartz64-A DTB, which
# hrdl's prebuilt kernel omits); every other package comes prebuilt from hrdl's
# binary repo. Runs the build natively if Arch tooling (makepkg + mkosi) is
# present; otherwise builds + runs an aarch64 Arch container so the host need not
# be Arch. On an aarch64 host that container is native speed (no emulation).
#
# Run as a NORMAL user — makepkg refuses root; the SD-imaging step sudo's itself.
#
# Examples:
#   ./build-and-flash.sh                     # build the SD image
#   ./build-and-flash.sh --device /dev/sdX   # build + flash to SD (confirms first)
#   ./build-and-flash.sh --skip-packages     # reuse the already-built kernel pkg
#   ./build-and-flash.sh --native            # force native (don't use Docker)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
REPO="$PWD"

UBOOT="${UBOOT:-}"
OUT="${OUT:-pinenote-quartz64.img}"
SIZE="${SIZE:-6G}"   # root (~3.5 GiB) + data (/home, rest); bump for a bigger /home
DEVICE=""
SKIP_PACKAGES=0
SKIP_MKOSI=0
FORCE=""                      # "" | native | docker
PACKAGES=(linux-pinenote-hrdl-git)
FWD=()                        # args to forward into the container

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --device)        DEVICE="$2"; FWD+=(--device "$2"); shift 2;;
    --uboot)         UBOOT="$2";  FWD+=(--uboot "$2");  shift 2;;
    --out)           OUT="$2";    FWD+=(--out "$2");    shift 2;;
    --size)          SIZE="$2";   FWD+=(--size "$2");   shift 2;;
    --skip-packages) SKIP_PACKAGES=1; FWD+=(--skip-packages); shift;;
    --skip-mkosi)    SKIP_MKOSI=1;    FWD+=(--skip-mkosi);    shift;;
    --native)        FORCE=native; shift;;
    --docker)        FORCE=docker; shift;;
    -h|--help)       usage 0;;
    *) echo "unknown arg: $1" >&2; usage 1;;
  esac
done

have_native() { command -v makepkg >/dev/null 2>&1 && command -v mkosi >/dev/null 2>&1; }

# ===========================================================================
# Container path: build + run containerbuild/, which re-invokes this script as a
# uid-matched non-root user with IN_CONTAINER=1 (so it takes the build path).
# ===========================================================================
run_in_container() {
  [ "$(id -u)" != 0 ] || { echo "run as a normal user (not root)" >&2; exit 1; }
  local engine="${CONTAINER_ENGINE:-}"
  if [ -z "$engine" ]; then command -v podman >/dev/null 2>&1 && engine=podman || engine=docker; fi
  command -v "$engine" >/dev/null 2>&1 || {
    echo "ERROR: no native mkosi/makepkg and no container engine ('$engine')." >&2
    echo "       Install docker/podman, or run on an Arch host with mkosi+base-devel." >&2; exit 1; }
  case "$(uname -m)" in
    aarch64|arm64) ;;
    *) echo "WARNING: host is $(uname -m), not aarch64 — the build will be EMULATED (very slow)." >&2;;
  esac

  local tag="${BUILD_TAG:-pinenote-build}"
  local base="${BUILD_IMAGE:-menci/archlinuxarm:latest}"
  echo "==> $engine build $tag (base: $base)"
  "$engine" build --build-arg "BUILD_IMAGE=$base" -t "$tag" "$REPO/containerbuild"

  echo "==> $engine run (privileged: kernel build + loop-device imaging need it)"
  exec "$engine" run --rm -it --privileged \
    -v "$REPO":/work -v /dev:/dev -w /work \
    -e BUILD_UID="$(id -u)" -e BUILD_GID="$(id -g)" \
    -e BUILD_ARGS="${FWD[*]}" \
    "$tag"
}

# ===========================================================================
# Build path (native host, or inside the container). Never runs as root.
# ===========================================================================
check_flash_device() {
  local dev="$1" dtype
  [ -b "$dev" ] || { echo "ERROR: $dev is not a block device" >&2; return 1; }
  dtype="$(lsblk -dno TYPE "$dev" 2>/dev/null || true)"
  if [ "$dtype" != disk ]; then
    echo "ERROR: $dev is a '${dtype:-?}', not a whole disk. This is a full-disk image" >&2
    echo "       (GPT + U-Boot at sector 64); flash the WHOLE card, never a partition." >&2
    return 1
  fi
  if ! ${SUDO:-} dd if="$dev" of=/dev/null bs=512 count=1 status=none 2>/dev/null; then
    echo "ERROR: $dev exists but cannot be opened (read test failed). If it's a USB device" >&2
    echo "       passed through to a VM, the passthrough has dropped — re-attach it." >&2
    return 1
  fi
}

do_build() {
  [ "$(id -u)" != 0 ] || { echo "ERROR: don't run the build as root — makepkg refuses." >&2; exit 1; }
  SUDO=""; command -v sudo >/dev/null && SUDO=sudo

  # Preflight the flash target BEFORE the (long) build, so a dead/wrong device
  # fails in seconds instead of after building the kernel + rootfs + image.
  [ -z "$DEVICE" ] || check_flash_device "$DEVICE" || exit 1

  # ---- 1. local kernel package -> mkosi.volatilepackages/ ----
  mkdir -p mkosi/mkosi.volatilepackages
  if [ "$SKIP_PACKAGES" = 0 ]; then
    for p in "${PACKAGES[@]}"; do
      echo "==> makepkg $p (this compiles the kernel — long)"
      ( cd "packages/$p" && makepkg --force --clean --skippgpcheck --noconfirm )
    done
  else
    echo "==> --skip-packages: reusing already-built kernel pkg"
  fi
  for p in "${PACKAGES[@]}"; do
    ls "packages/$p"/*.pkg.tar.* >/dev/null 2>&1 || { echo "ERROR: no built package in packages/$p (drop --skip-packages?)" >&2; exit 1; }
    cp packages/"$p"/*.pkg.tar.* mkosi/mkosi.volatilepackages/
  done
  echo "==> staged kernel pkg into mkosi/mkosi.volatilepackages/"

  # ---- 2. rootfs tar via mkosi (kernel from local pkg, rest from hrdl repo) ----
  ROOTFS="mkosi/arch_nonalarm_p6.tar.zst"
  if [ "$SKIP_MKOSI" = 0 ]; then
    # Seed pacman's cache subdir; with split cache/pkgcache dirs mkosi only
    # bind-mounts it when it already exists, and pacman refuses a missing cachedir.
    mkdir -p mkosi/mkosi.pkgcache/cache/pacman/pkg
    echo "==> mkosi (rootfs tar)"
    ( cd mkosi && mkosi --force )
  else
    echo "==> --skip-mkosi: reusing existing rootfs tar"
  fi
  [ -f "$ROOTFS" ] || { echo "ERROR: rootfs not found at $ROOTFS" >&2; exit 1; }

  # ---- 3. resolve U-Boot (build from source if absent; cached in builds/) ----
  if [ -z "$UBOOT" ]; then
    if [ -f builds/u-boot-rockchip.bin ]; then
      UBOOT=builds/u-boot-rockchip.bin
    else
      echo "==> no U-Boot found — building from source (one-time, cached in builds/)"
      ./scripts/build-uboot.sh "$REPO/builds/u-boot-rockchip.bin"
      UBOOT=builds/u-boot-rockchip.bin
    fi
  fi
  [ -f "$UBOOT" ] || { echo "ERROR: U-Boot not found at: $UBOOT (pass --uboot PATH)" >&2; exit 1; }
  echo "==> U-Boot: $UBOOT"

  # ---- 4. assemble bootable SD image (needs root: loop + mkfs) ----
  echo "==> assembling SD image $OUT"
  $SUDO ./scripts/mk-sdimage.sh --uboot "$UBOOT" --rootfs "$ROOTFS" --out "$OUT" --size "$SIZE"
  # Hand artifacts back to the invoking user (mk-sdimage ran under sudo).
  $SUDO chown "$(id -u):$(id -g)" "$OUT" "$ROOTFS" 2>/dev/null || true

  # ---- 5. optional flash ----
  if [ -n "$DEVICE" ]; then
    check_flash_device "$DEVICE" || exit 1
    echo; echo "About to OVERWRITE $DEVICE with $OUT:"
    $SUDO lsblk -o NAME,SIZE,MODEL,MOUNTPOINTS "$DEVICE" || true
    read -r -p "Type 'yes' to flash: " ans
    [ "$ans" = yes ] || { echo "aborted."; exit 1; }
    echo "==> flashing"
    $SUDO dd if="$OUT" of="$DEVICE" bs=4M conv=fsync status=progress
    $SUDO sync
    echo "==> flashed. Boot it and watch: picocom -b 115200 /dev/ttyACM0"
  else
    echo; echo "==> image ready: $OUT  ($(du -h "$OUT" 2>/dev/null | cut -f1))"
    echo "    flash with:  sudo dd if=$OUT of=/dev/sdX bs=4M conv=fsync status=progress"
    echo "    then watch:  picocom -b 115200 /dev/ttyACM0"
  fi
}

# --- pick a path ----------------------------------------------------------
case "$FORCE" in
  native) have_native || { echo "ERROR: --native but makepkg/mkosi not found" >&2; exit 1; }; do_build;;
  docker) run_in_container;;
  "")     if [ "${IN_CONTAINER:-0}" = 1 ] || have_native; then do_build; else run_in_container; fi;;
esac
