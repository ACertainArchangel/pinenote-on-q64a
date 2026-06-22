#!/usr/bin/env bash
# mk-sdimage.sh — assemble a bootable Quartz64-A microSD image (PineNote OS).
#
# PineNote OS (mkosi) builds only a ROOTFS tar (Bootable=false, Bootloader=none)
# meant to drop onto the PineNote's existing partitions. The Quartz64-A boots
# from SD with its own U-Boot, so this script supplies the boot layer the dist
# doesn't: it writes a Rockchip U-Boot at the 32 KiB offset, lays the Arch rootfs
# onto an ext4 root partition that U-Boot's extlinux path boots, and adds an empty
# ext4 'data' partition that the image mounts at /home (matching the PineNote).
#
# Run on Linux, as root (needs loop devices + mkfs). Example:
#   sudo ./scripts/mk-sdimage.sh \
#        --uboot builds/u-boot-rockchip.bin \
#        --rootfs mkosi/arch_nonalarm_p6.tar.zst \
#        --out pinenote-quartz64.img --size 4G
#
# Then flash:  sudo dd if=pinenote-quartz64.img of=/dev/sdX bs=4M conv=fsync status=progress
#
# Notes:
# - --uboot is the combined Rockchip image (idbloader + u-boot.itb) that goes at
#   sector 64. scripts/build-uboot.sh builds exactly this as
#   builds/u-boot-rockchip.bin (rkbin TPL rk3566_ddr_1056MHz_v1.18 +
#   rk3568_bl31_v1.43 + U-Boot 2024.10 quartz64-a-rk3566) with
#   CONFIG_BAUDRATE=115200 so the early console matches extlinux's 115200.
# - The rootfs label MUST be pinenote-root (extlinux.conf uses root=LABEL=).
set -euo pipefail

UBOOT="" ; ROOTFS="" ; OUT="pinenote-quartz64.img" ; SIZE="6G"
ROOT_LABEL="pinenote-root"
DATA_LABEL="data"                       # GPT partlabel for /home (fstab: by-partlabel/data)
ROOT_SIZE_MIB="${ROOT_SIZE_MIB:-3584}"  # root partition size (~3.5 GiB); the rest of the card -> data (/home)
UBOOT_SECTOR=64          # Rockchip idbloader offset (32 KiB)
PART1_START_MIB=16       # first partition starts at 16 MiB, clear of U-Boot

while [ $# -gt 0 ]; do
  case "$1" in
    --uboot)  UBOOT="$2"; shift 2;;
    --rootfs) ROOTFS="$2"; shift 2;;
    --out)    OUT="$2"; shift 2;;
    --size)   SIZE="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -n "$UBOOT" ]  || { echo "need --uboot <u-boot-rockchip.bin>" >&2; exit 2; }
[ -n "$ROOTFS" ] || { echo "need --rootfs <rootfs.tar[.zst]>" >&2; exit 2; }
[ -f "$UBOOT" ]  || { echo "no such file: $UBOOT" >&2; exit 2; }
[ -f "$ROOTFS" ] || { echo "no such file: $ROOTFS" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root (loop + mkfs)" >&2; exit 1; }

for t in sgdisk losetup mkfs.ext4 partprobe; do
  command -v "$t" >/dev/null || { echo "missing tool: $t" >&2; exit 1; }
done

echo "==> creating blank image $OUT ($SIZE)"
rm -f "$OUT"
truncate -s "$SIZE" "$OUT"

echo "==> GPT: ext4 root (${ROOT_SIZE_MIB}MiB) + ext4 data (rest -> /home), from ${PART1_START_MIB}MiB"
sgdisk --zap-all "$OUT" >/dev/null
# p1 = root (fixed size), p2 = data (fills the rest; mounted at /home per fstab's
# by-partlabel/data). Grow p2 by passing a larger --size; bump root with ROOT_SIZE_MIB.
sgdisk -n 1:${PART1_START_MIB}MiB:+${ROOT_SIZE_MIB}MiB -t 1:8300 -c 1:"$ROOT_LABEL" \
       -n 2:0:0                              -t 2:8300 -c 2:"$DATA_LABEL" "$OUT" >/dev/null

echo "==> writing U-Boot at sector $UBOOT_SECTOR"
dd if="$UBOOT" of="$OUT" bs=512 seek=$UBOOT_SECTOR conv=notrunc,fsync status=none

MNT=""   # defined up front so the EXIT trap is safe under `set -u` even when we
         # bail out before the mount below — otherwise the trap dies on the first
         # "$MNT" expansion ("MNT: unbound variable") and never reaches
         # `losetup -d`, leaking the loop device.
LOOP="$(losetup --find --show --partscan "$OUT")"
trap 'umount "$MNT" 2>/dev/null || true; losetup -d "$LOOP" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true' EXIT
partprobe "$LOOP" || true

# Wait for the partition node to appear. With --partscan the kernel + udev create
# ${LOOP}p1 ASYNCHRONOUSLY, and inside a container that races this script — so
# poll for it instead of checking once. (The old one-shot check fell straight
# through to the bogus "${LOOP}1", and mkfs.ext4 died with "/dev/loop01 does not
# exist".) Loop partitions are always ${LOOP}pN, never ${LOOP}N.
P1="${LOOP}p1"; P2="${LOOP}p2"
for _ in $(seq 1 100); do
  [ -e "$P1" ] && [ -e "$P2" ] && break
  partprobe "$LOOP" 2>/dev/null || true
  udevadm settle --timeout=1 2>/dev/null || true
  sleep 0.1
done
[ -e "$P1" ] || { echo "partition node $P1 never appeared (loop --partscan race)" >&2; exit 1; }
[ -e "$P2" ] || { echo "partition node $P2 never appeared (loop --partscan race)" >&2; exit 1; }

echo "==> mkfs.ext4 -L $ROOT_LABEL $P1  (root)"
mkfs.ext4 -q -L "$ROOT_LABEL" "$P1"
# data partition: empty ext4; /home is mounted onto it on first boot, where
# pinenote-create-user@archuser then creates archuser's home.
echo "==> mkfs.ext4 -L $DATA_LABEL $P2  (/home)"
mkfs.ext4 -q -L "$DATA_LABEL" "$P2"

MNT="$(mktemp -d)"
mount "$P1" "$MNT"

echo "==> extracting rootfs $ROOTFS"
case "$ROOTFS" in
  *.zst) zstd -dc "$ROOTFS" | tar -x -C "$MNT" ;;
  *.gz)  tar -xzf "$ROOTFS" -C "$MNT" ;;
  *)     tar -xf  "$ROOTFS" -C "$MNT" ;;
esac

if [ ! -f "$MNT/boot/extlinux/extlinux.conf" ]; then
  echo "WARNING: $MNT/boot/extlinux/extlinux.conf missing — U-Boot won't find a boot entry" >&2
fi

sync
echo "==> done: $OUT  (flash with: sudo dd if=$OUT of=/dev/sdX bs=4M conv=fsync status=progress)"
