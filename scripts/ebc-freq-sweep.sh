#!/usr/bin/env bash
# ebc-freq-sweep.sh — sweep the rockchip_ebc data clock and re-init the panel at
# each, so you can SEE which clock drives the TWE1030NE48 cleanly.
#
# Why reload the module instead of poking sysfs? dclk_select only takes effect
# during a modeset (rockchip_ebc_set_dclk runs at probe/atomic_enable), and the
# only thing that has ever driven this panel is the driver's init at boot. So we
# reload rockchip_ebc with a new dclk_select each step: that re-runs set_dclk AND
# re-inits the panel — a real, observable drive at that clock.
#
# RUN AS ROOT ON THE SERIAL CONSOLE. It tears down the e-ink/fb console to let the
# module unload; the serial shell (ttyS2) is unaffected.
#
#   dclk_select: -1 = panel mode clock (~125 MHz -> ~15.7 MHz source, in spec),
#                 0 = 200 MHz (-> 25 MHz source, at the datasheet max),
#                 1 = 250 MHz (-> 31 MHz source, OVER the datasheet's 25 MHz max).
#
# Env: FREQS="-1 0 1"  HOLD=6
set -u
[ "$(id -u)" = 0 ] || { echo "run as root on the serial console" >&2; exit 1; }

# Parse into SWEEP (NOT back into FREQS): assigning to FREQS makes it an array, and
# on a re-run in the same shell ${FREQS:-...} would then expand to just FREQS[0].
read -r -a SWEEP <<< "${FREQS:--1 0 1}"
HOLD="${HOLD:-6}"
PARAMS="${EXTRA_PARAMS:-limit_fb_blits=4 temp_override=25}"
# limit_fb_blits=4: allow a FEW frames (0 blocks ALL content -> nothing draws), capping how hard we drive.
# temp_override=25: pin the temperature — flaky/-110 tps65185 reads otherwise make schedule_advance_neon
# hang (RCU stall), which masks the frequency test entirely.

fb_console() {   # $1 = 0 (unbind) | 1 (rebind) the framebuffer console
  for v in /sys/class/vtconsole/vtcon*; do
    grep -q 'frame buffer' "$v/name" 2>/dev/null && echo "$1" > "$v/bind" 2>/dev/null
  done
}

echo "==> stopping greetd + releasing the fb console (so the module can unload)"
systemctl stop greetd 2>/dev/null
sleep 1
fb_console 0
modprobe -r rockchip_ebc 2>/dev/null \
  || { echo "ERROR: rockchip_ebc still in use — something else holds the DRM device." >&2; \
       echo "       check: lsof /dev/dri/* ; fuser /dev/fb0" >&2; exit 1; }

for f in "${SWEEP[@]}"; do
  echo "==================== dclk_select=$f ===================="
  modprobe -r rockchip_ebc 2>/dev/null
  modprobe rockchip_ebc dclk_select="$f" $PARAMS    # re-probe + init at this clock
  fb_console 1                                       # console draw nudges a refresh
  # push a full WHITE frame so there's clean content to judge (16bpp = 1872*1404*2 bytes)
  tr '\0' '\377' < /dev/zero | head -c 5256576 > /dev/fb0 2>/dev/null
  echo "   watch the panel for ${HOLD}s ..."
  sleep "$HOLD"
done

echo "==> sweep done; reloading at default. (re-enable the desktop: systemctl start greetd)"
modprobe -r rockchip_ebc 2>/dev/null
modprobe rockchip_ebc
fb_console 1
