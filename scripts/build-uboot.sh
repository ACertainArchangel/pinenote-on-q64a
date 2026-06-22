#!/usr/bin/env bash
# build-uboot.sh — build a Quartz64-A U-Boot (u-boot-rockchip.bin) at 115200,
# from source, so the image build is self-contained.
#
# Known-good parameters for this board:
#   U-Boot v2024.10, quartz64-a-rk3566_defconfig,
#   rkbin TPL rk3566_ddr_1056MHz_v1.18 + BL31 rk3568_bl31_v1.43,
#   CONFIG_BAUDRATE=115200 (the Arduino UNO bridge can't clock 1.5M).
#
# Native aarch64 build (no cross). Output is cached in builds/ and reused.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
REPO="$PWD"

OUT="${1:-$REPO/builds/u-boot-rockchip.bin}"
WORK="${UBOOT_WORK:-$REPO/builds/uboot-src}"
UBOOT_URL="${UBOOT_URL:-https://github.com/u-boot/u-boot.git}"
UBOOT_REF="${UBOOT_REF:-v2024.10}"
RKBIN_URL="${RKBIN_URL:-https://github.com/rockchip-linux/rkbin.git}"
DEFCONFIG="${UBOOT_DEFCONFIG:-quartz64-a-rk3566_defconfig}"
BAUD=115200

mkdir -p "$WORK" "$(dirname "$OUT")"

[ -d "$WORK/rkbin/.git" ]  || git clone --depth 1 "$RKBIN_URL"  "$WORK/rkbin"
[ -d "$WORK/u-boot/.git" ] || git clone --depth 1 --branch "$UBOOT_REF" "$UBOOT_URL" "$WORK/u-boot"

# DDR-init TPL + ATF BL31 blobs: prefer the v1-pinned versions, else the newest
# matching blob in the current rkbin (filenames drift over time).
pick() { ls -1 "$WORK"/rkbin/$1 2>/dev/null | sort -V | tail -1; }
TPL="$WORK/rkbin/bin/rk35/rk3566_ddr_1056MHz_v1.18.bin"
[ -f "$TPL" ]  || TPL="$(pick 'bin/rk35/rk3566_ddr_*.bin')"
BL31="$WORK/rkbin/bin/rk35/rk3568_bl31_v1.43.elf"
[ -f "$BL31" ] || BL31="$(pick 'bin/rk35/rk3568_bl31_*.elf')"
[ -n "${TPL:-}"  ] && [ -f "$TPL" ]  || { echo "no rk3566 DDR TPL blob in rkbin" >&2; exit 1; }
[ -n "${BL31:-}" ] && [ -f "$BL31" ] || { echo "no rk3568 BL31 blob in rkbin" >&2; exit 1; }
echo "==> TPL  = $TPL"
echo "==> BL31 = $BL31"

cd "$WORK/u-boot"
# SWIG 4.3.0 gave SWIG_Python_AppendOutput a third (is_void) argument, which
# breaks U-Boot 2024.10's bundled dtc pylibfdt — it calls the old 2-arg form and
# fails to compile ("too few arguments to function 'SWIG_Python_AppendOutput'";
# pylibfdt is pulled in by binman to assemble u-boot-rockchip.bin). The dtc
# upstream fix is to call SWIG_AppendOutput instead: the 2-arg compatibility
# macro SWIG >=4.3 provides. Our build image ships swig 4.4. Idempotent — a no-op
# once patched. Patch libfdt.i_shipped (the git-tracked source): kbuild
# regenerates libfdt.i from it on every build and `make mrproper` deletes
# libfdt.i, so editing libfdt.i directly would be clobbered.
sed -i 's/SWIG_Python_AppendOutput/SWIG_AppendOutput/g' scripts/dtc/pylibfdt/libfdt.i_shipped
make mrproper
make "$DEFCONFIG"
./scripts/config --set-val BAUDRATE "$BAUD"   # force 115200, not the 1.5M default
make olddefconfig
BL31="$BL31" ROCKCHIP_TPL="$TPL" make -j"$(nproc)"

[ -f u-boot-rockchip.bin ] || { echo "build produced no u-boot-rockchip.bin" >&2; exit 1; }
cp -f u-boot-rockchip.bin "$OUT"
echo "==> U-Boot ready: $OUT  ($DEFCONFIG, $BAUD)"
