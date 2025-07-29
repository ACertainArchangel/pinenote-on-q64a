#!/usr/bin/env -S uv run --script --with pylibi2c,crcmod

# Prerequisites: uv or python modules crcmod and pylibi2c
# Before running this script: sudo modprobe -r cyttsp5; chmod o+rw /dev/i2c-5
# After running this script successfully: sudo modprobe cyttsp5; chmod o-rw /dev/i2c-5

import struct
import time

import crcmod
import pylibi2c

BUS = '/dev/i2c-5'
DEV_ADDR = 0x24
REG_ADDR = 4

HID_APP_OUTPUT_REPORT_ID = 0x2f

CMD_SUSPEND_SCANNING = 0x03
CMD_RESUME_SCANNING = 0x04
CMD_VERIFY_CONFIG_BLOCK_CRC = 0x20
CMD_GET_CONFIG_ROW_SIZE = 0x21
CMD_READ_CONF_BLOCK = 0x22
CMD_WRITE_CONF_BLOCK = 0x23

CYTTSP5_SECURITY_KEY = bytes([0xA5, 0x01, 0x02, 0x03, 0xFF, 0xFE, 0xFD, 0x5A])

BLOCK_SIZE = 128

# Suspend scanning
# i2ctransfer 5 w7@0x24 0x04 0x00 5 0 0x2f 0 3

# i2ctransfer 5 r512@0x24 |xxd -r -p > read_after_suspend

# Read first config row
# i2ctransfer 5 w12@0x24 0x04 0x00 0x0a 0x00 0x2f 0x00 0x22 0x00 0x00 0x80 0x00 0x00

dev = pylibi2c.I2CDevice(BUS, DEV_ADDR, iaddr_bytes=0, page_bytes=512)

def send(cmd, payload = None, sleep_ms: int = 200):
    payload = payload or b''
    cmd_buf = struct.pack('<HHBBB', REG_ADDR, 5 + len(payload), HID_APP_OUTPUT_REPORT_ID, 0, cmd) + payload
    _l = dev.ioctl_write(0, cmd_buf)
    print(_l, cmd_buf.hex(' '))
    time.sleep(sleep_ms / 1000)
    resp = dev.ioctl_read(0, 512)
    (length,) = struct.unpack_from('<H', resp)
    print(resp[:length].hex(' '))
    if length < 5:
        raise ValueError('Length error')
    if resp[4] & 0b111111 != cmd:
        raise ValueError('Command codes do not match')
    return resp[:length]

def suspend():
    return send(CMD_SUSPEND_SCANNING, sleep_ms=1000)

def resume():
    return send(CMD_RESUME_SCANNING)

def read_config_block(block_idx: int, length: int = BLOCK_SIZE):
    resp = send(CMD_READ_CONF_BLOCK, struct.pack('<HHB', block_idx, length, 0), sleep_ms=400)
    if status := resp[5]:
        raise ValueError(f"{status=} is not zero")
    if (read_ebid := resp[6]) or resp[9]:
        raise ValueError(f"{read_ebid=} or {resp[9]=} not zero")
    (read_length,) = struct.unpack_from('<H', resp, 7)
    block = resp[10:10+min(read_length, length)]
    (crc,) = struct.unpack_from('<H', resp, 10 + read_length)
    return block
    # TODO: check crc

def read_config():
    block_idx = 0
    config = bytearray()
    config += read_config_block(block_idx, BLOCK_SIZE)
    block_idx += 1
    (config_length,) = struct.unpack_from('<H', config)
    # CRC
    config_length += 2
    while len(config) < config_length:
        config += read_config_block(block_idx, min(BLOCK_SIZE, config_length - len(config)))
        block_idx += 1
    return config

def write_config_block(block_idx, data):
    crc = crcmod.predefined.PredefinedCrc("crc-ccitt-false").new()
    crc.update(data)
    cmd_buf = struct.pack('<HHB', block_idx, len(data), 0) + data + CYTTSP5_SECURITY_KEY + crc.digest()[::-1]
    resp = send(CMD_WRITE_CONF_BLOCK, cmd_buf)
    if resp[5] != 0:
        raise ValueError('Write command failed')

def write_config(config):
    block_idx = 0
    bytes_written = 0
    while bytes_written < len(config):
        write_length = min(BLOCK_SIZE, len(config) - bytes_written )
        data = config[BLOCK_SIZE * block_idx:][:write_length]
        write_config_block(block_idx, data)
        block_idx += 1
        bytes_written += write_length

def write_config_first_and_last_block(config):
    write_config_block(0, config[:BLOCK_SIZE])
    last_block_idx = (len(config) + BLOCK_SIZE - 1) // BLOCK_SIZE - 1
    if last_block_idx > 0:
        write_config_block(last_block_idx, config[BLOCK_SIZE * last_block_idx:])

def verify_crc():
    resp = send(CMD_VERIFY_CONFIG_BLOCK_CRC, bytes([0]))
    calculated_crc, stored_crc = struct.unpack_from('<HH', resp, 6)
    if calculated_crc != stored_crc:
        raise ValueError(f'CRCs mismatch {calculated_crc=} {stored_crc=}')

if __name__ == '__main__':
    suspend()

    config = read_config()
    with open(f'config_{config[0x42]}_{config[-2:].hex()}.bin', 'wb') as f:
        f.write(config)
    # Enable ten finger input
    config[0x42] = 10
    # Recompute CRC
    crc = crcmod.predefined.PredefinedCrc("crc-ccitt-false").new()
    crc.update(config[:-2])
    config[-2:] = crc.digest()[::-1]
    with open(f'config_{config[0x42]}_{config[-2:].hex()}.bin', 'wb') as f:
        f.write(config)

    write_config_first_and_last_block(config)
    verify_crc()
