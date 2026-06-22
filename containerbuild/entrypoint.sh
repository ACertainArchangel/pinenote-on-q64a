#!/usr/bin/env bash
# Runs INSIDE the Arch build container (as root). Creates/uses a non-root user
# whose uid/gid match the host (so bind-mounted files stay yours), gives it
# passwordless sudo, then runs build-and-flash.sh as that user — makepkg refuses
# to run as root, and build-and-flash.sh sudo's only the SD-imaging step.
set -euo pipefail

# Pin a sane PATH: some base images export a PATH the exec'd shell doesn't
# inherit cleanly, which is why sudo/tools can read as "not found".
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

echo "==> tools: $(command -v bash pacman sudo runuser makepkg clang mkosi 2>/dev/null | tr '\n' ' ')"
command -v sudo >/dev/null 2>&1 || { echo "==> installing sudo"; pacman -Sy --noconfirm --needed sudo; }

BUILD_UID="${BUILD_UID:-1000}"
BUILD_GID="${BUILD_GID:-1000}"

# Reuse whatever user already owns BUILD_UID (e.g. ALARM's 'alarm' user at 1000)
# so we don't fight over the uid; otherwise create 'builder'.
U="$(getent passwd "$BUILD_UID" | cut -d: -f1 || true)"
if [ -z "$U" ]; then
  getent group "$BUILD_GID" >/dev/null 2>&1 || groupadd -g "$BUILD_GID" builder
  useradd -u "$BUILD_UID" -g "$BUILD_GID" -m -s /bin/bash builder
  U=builder
fi

mkdir -p /etc/sudoers.d
grep -qs '^@includedir /etc/sudoers.d' /etc/sudoers || echo '@includedir /etc/sudoers.d' >> /etc/sudoers
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$U" > /etc/sudoers.d/pinenote-builder
chmod 0440 /etc/sudoers.d/pinenote-builder

H="$(getent passwd "$U" | cut -d: -f6)"
[ -d "$H" ] || { mkdir -p "$H"; chown "$BUILD_UID:$BUILD_GID" "$H"; }

cd /work
echo "==> building as user '$U' (uid $BUILD_UID)"
echo "==> args: ${BUILD_ARGS:-<none>}"
# Drop privileges with runuser (util-linux, always present). IN_CONTAINER tells
# build-and-flash.sh it's already inside the container (don't re-dispatch to Docker).
exec runuser -u "$U" -- env IN_CONTAINER=1 bash -lc 'cd /work && ./build-and-flash.sh $BUILD_ARGS'
