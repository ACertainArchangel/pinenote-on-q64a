# PineNote Arch Linux

![Screenshot of an sway desktop with with a waybar explaining various elements](doc/screenshot_sway_waybar.png)

This repository contains all utilities required to create an Arch Linux system for the PineNote using
- `hrdl`'s custom `rockchip_ebc` kernel,
- `greetd`, `sway`, `gtkgreet`, and `squeekboard` as greeter,
- `sway, waybar, nwg-menu, squeekboard` including an integration with the `rockchip_ebc` driver via `ioctl`, `dbus`, and `sway IPC`.

## Custom packages:
See [packages/](packages/):

- [brcm-firmware-pinenote](packages/brcm-firmware-pinenote/): firmware for the WiFi/bluetooth module extracted from the `linux-firmware` package to save ~270 MB of disc space.
- [linux-pinenote-hrdl](packages/linux-pinenote-hrdl/): the kernel containing `hrdl`'s `rockchip_ebc` driver from their [tree](https://git.sr.ht/~hrdl/linux). Can be built incrementally using `makepkg -e`.
- [pinenote-arch](packages/pinenote-arch): various configuration files and helpers from this repository.
- [pinenote-hrdl-sway-meta](packages/pinenote-hrdl-sway-meta): a meta package to ensure compatibility between helpers, kernel, and wayland compositor
- [pneink-theme-git](packages/pneink-theme-git): a package for https://github.com/PNDeb/PNEink

## Distribution image
To create a preconfigured distribution image:

1. Build the packages in `packages/` and place the resulting files into `mkosi/mkosi.packages/` using `makepkg -d`.
2. Download and build the following packages from AUR or remove them from `mkosi/mkosi.conf`:
  - `fonts-droid-fallback`
  - `fonts-noto-hinted`
  - `koreader-bin`
  - `lisgd`
  - `rot8-git`
  - `xournalpp-git`: better multitouch and reduced damage regions in menu
3. Build `arch.tar.zst` on an `aarch64` device: `cd mkosi; mkosi`

## First boot

1. Extract image onto `os2`. Make sure it has a suitable filesystem.
  - `mount /dev/disk/by-partlabel/os2 /mnt && tar -xf arch.tar.zst -C /mnt`
2. If you don't have a waveform partition, copy your waveform to `/mnt/usr/lib/firmware/rockchip`
3. Reboot into os2. During the first boot `ebc.wbf` is extracted from the waveform partition, converted to `custom_wf.bin`, included in a new initial ramfs, and a new user `archuser` with password `password` is created and logged in automatically.
4. Change the passwords for `archuser`, `user`, and `root` (default password: `rootpass`). To disable passwordless login, remove `nopasswdlogin` from `user` and `archuser` and remove `initial_session.user` from `/etc/greetd/config.toml`.

## Modifications

### (Re)drawing behaviour
To change a wayland-native application's rendering behaviour, configure its `app_id` (`swaymsg -t get_tree |grep app_id`) statically in `/usr/bin/sway_dbus_integration.py` or configure it via dbus. See `sway_dbus_integration.py` for details.

### Installation to another partition
To install to another partition, modify `/boot/extlinux/extlinux.conf`.

### Pen buttons (developer edition)
To map double and triple button presses for the developer edition's BLE pen, ensure `ws8100-pen.ko` is loaded, install aur/evsieve, and adopt [setup_evsieve.sh](https://raw.githubusercontent.com/PNDeb/pinenote-debian-image/e83669307593938b202805549059d0516a8d09f5/overlays/root/setup_evsieve.sh).

### Larger text
The output scale can be set in `/etc/sway_hrdl/sway/config` (default: `output * scale 1`). However, non-integer scale factors result in noticable worse performance e.g. when using xournalpp. Instead font sizes can be increased on a per-framework / per-application level:

```
# GTK3
gsettings set org.gnome.desktop.interface font-name 'Adwaita Sans 15'

# Kitty
echo font_size 15 >> ~/.config/kitty/kitty.conf
```

### Bluetooth
For CLI usage: `sudo pacman -Sy bluez-tools; systemctl enable --now bluetooth` and configure va `bluetoothctl`. For a GUI approach: `sudo pacman -Sy blueman`, run `systemctl enable --now bluetooth`, and run `blueman-manager`, optionally adding something like

```
exec blueman-applet
# Optional, for a floating blueman-manager window
# for_window [app_id="blueman-manager"] floating enable
```

to `/etc/sway_hrdl/sway/config`.
