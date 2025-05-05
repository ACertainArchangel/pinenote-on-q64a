#!/usr/bin/env python3

import rockchip_ebc_custom_ioctl
import pathlib
import time

p = pathlib.Path(f'~/{int(time.time())}').expanduser()
p.mkdir(parents=True)
rockchip_ebc_custom_ioctl.extract_fbs_to_dir(p)
