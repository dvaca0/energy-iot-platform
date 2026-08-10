"""Dependency-free I2C access via ioctl.

WHY NOT smbus2
    The collector runs in a venv containing only `requests`. The canonical
    heartbeat is produced by the collector, and it must be able to read UPS
    state. Adding smbus2/psutil to that venv would make the hardening package
    depend on a pip install succeeding on every node in the fleet. This module
    talks to /dev/i2c-N through the kernel's ioctl interface using nothing but
    the standard library, so it works in any interpreter on any node.

Implements SMBus-equivalent read_byte_data / read_word_data / write_byte_data
using I2C_RDWR, which issues a proper repeated START between the register
write and the data read (a plain write()+read() would insert a STOP, which
some devices tolerate and some do not).
"""

from __future__ import annotations

__version__ = "1.0.0"

import ctypes
import fcntl
import os
from typing import Optional

I2C_RDWR = 0x0707
I2C_M_RD = 0x0001


class _Msg(ctypes.Structure):
    _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16),
                ("len", ctypes.c_uint16), ("buf", ctypes.POINTER(ctypes.c_uint8))]


class _IoctlData(ctypes.Structure):
    _fields_ = [("msgs", ctypes.POINTER(_Msg)), ("nmsgs", ctypes.c_uint32)]


class I2CError(OSError):
    pass


class I2CBus:
    """Minimal SMBus-compatible surface. Use as a context manager."""

    def __init__(self, bus: int = 1):
        self.bus = bus
        self.path = f"/dev/i2c-{bus}"
        self._fd: Optional[int] = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "I2CBus":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        if self._fd is None:
            self._fd = os.open(self.path, os.O_RDWR)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    @staticmethod
    def available(bus: int = 1) -> bool:
        return os.path.exists(f"/dev/i2c-{bus}")

    # -- transfers ---------------------------------------------------------
    def _xfer(self, msgs: list) -> None:
        if self._fd is None:
            raise I2CError("bus not open")
        arr = (_Msg * len(msgs))(*msgs)
        data = _IoctlData(msgs=arr, nmsgs=len(msgs))
        fcntl.ioctl(self._fd, I2C_RDWR, data)

    def read_bytes(self, addr: int, reg: int, count: int) -> bytes:
        """Write `reg`, repeated START, read `count` bytes."""
        wbuf = (ctypes.c_uint8 * 1)(reg & 0xFF)
        rbuf = (ctypes.c_uint8 * count)()
        self._xfer([
            _Msg(addr=addr, flags=0, len=1,
                 buf=ctypes.cast(wbuf, ctypes.POINTER(ctypes.c_uint8))),
            _Msg(addr=addr, flags=I2C_M_RD, len=count,
                 buf=ctypes.cast(rbuf, ctypes.POINTER(ctypes.c_uint8))),
        ])
        return bytes(rbuf)

    def read_byte_data(self, addr: int, reg: int) -> int:
        return self.read_bytes(addr, reg, 1)[0]

    def read_word_be(self, addr: int, reg: int) -> int:
        """16-bit big-endian read (INA219 and most sensors are big-endian)."""
        b = self.read_bytes(addr, reg, 2)
        return (b[0] << 8) | b[1]

    def write_byte_data(self, addr: int, reg: int, value: int) -> None:
        wbuf = (ctypes.c_uint8 * 2)(reg & 0xFF, value & 0xFF)
        self._xfer([_Msg(addr=addr, flags=0, len=2,
                         buf=ctypes.cast(wbuf, ctypes.POINTER(ctypes.c_uint8)))])

    def ping(self, addr: int) -> bool:
        """True if a device ACKs at `addr`. Read-only, no side effects."""
        rbuf = (ctypes.c_uint8 * 1)()
        try:
            self._xfer([_Msg(addr=addr, flags=I2C_M_RD, len=1,
                             buf=ctypes.cast(rbuf,
                                             ctypes.POINTER(ctypes.c_uint8)))])
            return True
        except OSError:
            return False

    def scan(self, start: int = 0x03, end: int = 0x77) -> list:
        return [a for a in range(start, end + 1) if self.ping(a)]


def signed16(value: int) -> int:
    return value - 0x10000 if value > 0x7FFF else value
