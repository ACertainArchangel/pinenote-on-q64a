# PineNote Arch Linux

![Screenshot of an sway desktop with with a waybar explaining various elements](doc/screenshot_sway_waybar.png)

This repository contains all utilities required to create an Arch Linux system for the PineNote using
- `hrdl`'s custom `rockchip_ebc` kernel,
- `greetd`, `sway`, `gtkgreet`, and `squeekboard` as greeter,
- `sway, waybar, nwg-menu, squeekboard` including an integration with the `rockchip_ebc` driver via `ioctl`, `dbus`, and `sway IPC`.

## Migration from ALARM to unofficial aarch64 Arch Linux port

1. Download and locally sign drzee's packaging key
```
curl https://arch-linux-repo.drzee.net/arch/extra/os/aarch64/public.key |sudo pacman-key --add
sudo pacman-key --lsign-key 9B2C213B21883BB65CE2FB900CF25682E6BA0751
```
2. Replace AUR mirror in `/etc/pacman.d/mirrorlist` with `https://arch-linux-repo.drzee.net/arch/$repo/os/$arch`
3. Remove repositories / sections `[aur]` and `[alarm]` from `/etc/pacman.conf`
4. Reinstall all packages: `pacman -Qqn |sudo pacman -Sy -`

## Custom packages:
See [packages/](packages/):

- [brcm-firmware-pinenote](packages/brcm-firmware-pinenote/): firmware for the WiFi/bluetooth module extracted from the `linux-firmware` package to save ~270 MB of disc space.
- [linux-pinenote-hrdl](packages/linux-pinenote-hrdl/): the kernel containing `hrdl`'s `rockchip_ebc` driver from their [tree](https://git.sr.ht/~hrdl/linux). Can be built incrementally using `makepkg -e`.
- [pinenote-arch](packages/pinenote-arch): various configuration files and helpers from this repository.
- [pinenote-hrdl-sway-meta](packages/pinenote-hrdl-sway-meta): a meta package to ensure compatibility between helpers, kernel, and wayland compositor
- [pneink-theme-git](packages/pneink-theme-git): a package for https://github.com/PNDeb/PNEink

## Distribution image
To create a preconfigured distribution image, ensure `archlinux-keyring, mkosi, qemu-system-aarch64` are installed. To use precompiled packages built and signed by `hrdl`'s, simply run `cd mkosi; mkosi`.

To create a preconfigured distribution image without relying on `hrdl`'s prebuilt packages and repositories:

1. Build the packages in `packages/` and place the resulting files into `mkosi/mkosi.volatilepackages/` using `makepkg -d`.
2. Download and build the following packages from AUR or remove them from `mkosi/mkosi.conf`:
  - `fonts-droid-fallback`
  - `fonts-noto-hinted`
  - `koreader-bin`
  - `lisgd`
  - `rot8-git`
  - `xournalpp-git`: better multitouch and reduced damage regions in menu
3. Remove the reference to `hrdl`'s key from `mkosi/mkosi.finalize.chroot`, remove `hrdl` repository/section from `mkosi/mkosi.sandbox/etc/pacman.conf`, and remove `mkosi/mkosi.sandbox/usr/share/pacman/keyrings/hrdl-trusted`.
4. Ensure `archlinux-keyring, mkosi, qemu-system-aarch64` are installed. To use precompiled packages built and signed by `hrdl`'s, simply run `cd mkosi; mkosi`.

A 709 MiB image can be downloaded from `https://files.hrdl.eu/arch_nonalarm.tar.zst{,sig}`. This string contains two URLs. A 769 MiB pre-built ALARM image and its signature can be downloaded from `https://files.hrdl.eu/arch.tar.zst{,sig}`. This string contains two URLs.

## First boot

1. Extract image onto `os2`. Make sure it has a suitable filesystem.
    - `sudo sh -c 'mount /dev/disk/by-partlabel/os2 /mnt && tar -xf arch.tar.zst -C /mnt && sync'`
2. If you don't have a waveform partition, copy your waveform to `/mnt/usr/lib/firmware/rockchip/`
3. Reboot into os2. During the first boot `ebc.wbf` is extracted from the waveform partition, converted to `custom_wf.bin`, included in a new initial ramfs, and a new user `archuser` with password `password` is created and logged in automatically.
4. Change the passwords for `archuser`, `user`, and `root` (default password: `rootpass`). To disable passwordless login, remove `nopasswdlogin` from `user` and `archuser` and remove the entire `initial_session` section from `/etc/greetd/config.toml`.
5. Optionally, configure hrdl's repository to receive kernel updates, precompiled AUR updates (`xournalpp-git` in particular), and sway/dbus-related integrations:
    1. Add hrdl's key: `sudo pacman-key --recv-keys A759E2F745AE017764D35BF8AC50F8C2F0157FEA` or `curl https://meta.sr.ht/~hrdl.pgp |sudo pacman-key --add`
    2. Sign hrdl's key: `sudo pacman-key --lsign-key A759E2F745AE017764D35BF8AC50F8C2F0157FEA`
    3. Add the repository: `echo -e '[hrdl]\nServer = https://files.hrdl.eu/pnarch' |sudo tee -a /etc/pacman.conf`

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

### Waybar font unreadable
Run `sudo pacman -Sy otf-font-awesome` to install `otf-font-awesome`.

### Boot OS2 by default instead of OS1
```
sudo pacman -S parted
sudo parted --script /dev/mmcblk0 set 5 legacy_boot off set 6 legacy_boot on
```
