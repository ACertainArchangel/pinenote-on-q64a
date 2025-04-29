#!/bin/sh

set -e

IN=/dev/disk/by-partlabel/waveform
OUT=/usr/lib/firmware/rockchip/ebc.wbf

mkdir -p /usr/lib/firmware/rockchip
size=$(hexdump --skip 4 --length 4 "${IN}" --format '"%u"')
head -c "${size}" "${IN}" > "${OUT}"
