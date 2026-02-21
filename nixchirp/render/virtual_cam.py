"""Virtual camera output via v4l2loopback.

Writes RGB24 frames to a v4l2loopback device using direct V4L2 ioctl calls.
Requires the v4l2loopback kernel module loaded with exclusive_caps=1:

    sudo modprobe v4l2loopback exclusive_caps=1 card_label=NixChirp

No external Python dependencies — uses only stdlib ctypes and fcntl.
"""

from __future__ import annotations

import ctypes
import fcntl
import logging
import os
import subprocess
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# V4L2 constants and structures (stable Linux kernel ABI)
# ---------------------------------------------------------------------------

V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
V4L2_FIELD_NONE = 1
V4L2_COLORSPACE_SRGB = 8

V4L2_CAP_VIDEO_OUTPUT = 0x00000002


def _fourcc(a: str, b: str, c: str, d: str) -> int:
    return ord(a) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24)


V4L2_PIX_FMT_RGB24 = _fourcc("R", "G", "2", "4")


class _v4l2_pix_format(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelformat", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("bytesperline", ctypes.c_uint32),
        ("sizeimage", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("priv", ctypes.c_uint32),
    ]


class _v4l2_format_union(ctypes.Union):
    # The kernel union includes struct v4l2_window which has pointer members,
    # requiring 8-byte alignment on x86_64.  c_void_p forces matching alignment
    # so ctypes inserts the same padding the kernel does (208 bytes total, not 204).
    _fields_ = [
        ("pix", _v4l2_pix_format),
        ("raw_data", ctypes.c_uint8 * 200),
        ("_ptr_align", ctypes.c_void_p),
    ]


class _v4l2_format(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("fmt", _v4l2_format_union),
    ]


class _v4l2_capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_char * 16),
        ("card", ctypes.c_char * 32),
        ("bus_info", ctypes.c_char * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


def _ior(type_char: str, nr: int, size: int) -> int:
    """Compute _IOR ioctl number."""
    return (2 << 30) | (ord(type_char) << 8) | nr | (size << 16)


def _iowr(type_char: str, nr: int, size: int) -> int:
    """Compute _IOWR ioctl number."""
    return ((2 | 1) << 30) | (ord(type_char) << 8) | nr | (size << 16)


VIDIOC_QUERYCAP = _ior("V", 0, ctypes.sizeof(_v4l2_capability))
VIDIOC_S_FMT = _iowr("V", 5, ctypes.sizeof(_v4l2_format))


# ---------------------------------------------------------------------------
# VirtualCamera
# ---------------------------------------------------------------------------

class VirtualCamera:
    """Writes frames to a v4l2loopback virtual camera device."""

    def __init__(self, device: str, width: int, height: int) -> None:
        self._device = device
        self._width = width
        self._height = height
        self._fd: int | None = None
        self._status: str = "Not started"
        self._rgb_buf: np.ndarray | None = None

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    @property
    def status(self) -> str:
        return self._status

    def open(self) -> bool:
        """Open the v4l2loopback device and set the pixel format.

        Returns True on success, False on failure (with status set).
        """
        if self._fd is not None:
            return True

        if not os.path.exists(self._device):
            self._status = f"Device not found: {self._device}"
            logger.warning("Virtual camera: %s", self._status)
            return False

        try:
            self._fd = os.open(self._device, os.O_RDWR)
        except PermissionError:
            self._status = f"Permission denied: {self._device}"
            logger.warning("Virtual camera: %s", self._status)
            return False
        except OSError as e:
            self._status = f"Cannot open {self._device}: {e}"
            logger.warning("Virtual camera: %s", self._status)
            return False

        # Verify this is a v4l2loopback output device
        cap = _v4l2_capability()
        try:
            fcntl.ioctl(self._fd, VIDIOC_QUERYCAP, cap)
            if not (cap.device_caps & V4L2_CAP_VIDEO_OUTPUT):
                self._status = f"{self._device} is not an output device"
                logger.warning("Virtual camera: %s (caps=0x%x)", self._status, cap.device_caps)
                os.close(self._fd)
                self._fd = None
                return False
            logger.debug("V4L2 device: driver=%s card=%s caps=0x%x",
                         cap.driver, cap.card, cap.device_caps)
        except OSError as e:
            logger.debug("QUERYCAP failed (non-fatal): %s", e)

        # Set V4L2 pixel format
        fmt = _v4l2_format()
        fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT
        fmt.fmt.pix.width = self._width
        fmt.fmt.pix.height = self._height
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_RGB24
        fmt.fmt.pix.field = V4L2_FIELD_NONE
        fmt.fmt.pix.bytesperline = self._width * 3
        fmt.fmt.pix.sizeimage = self._width * self._height * 3
        fmt.fmt.pix.colorspace = V4L2_COLORSPACE_SRGB

        try:
            fcntl.ioctl(self._fd, VIDIOC_S_FMT, fmt)
        except OSError as e:
            self._status = f"Format setup failed: {e}"
            logger.warning("Virtual camera: %s", self._status)
            if e.errno == 22:  # EINVAL
                logger.info("Hint: reload with: sudo modprobe -r v4l2loopback && "
                            "sudo modprobe v4l2loopback exclusive_caps=1")
            os.close(self._fd)
            self._fd = None
            return False

        self._rgb_buf = np.empty((self._height, self._width, 3), dtype=np.uint8)

        self._status = "Active"
        logger.info("Virtual camera opened: %s (%dx%d RGB24)",
                     self._device, self._width, self._height)
        return True

    def write_frame(self, rgba: np.ndarray, bg_color: tuple[int, int, int] = (0, 255, 0)) -> None:
        """Write an RGBA frame to the virtual camera.

        Composites the RGBA frame onto a solid background color and writes
        the resulting RGB24 data to the device.
        """
        if self._fd is None or self._rgb_buf is None:
            return

        h, w = rgba.shape[:2]
        if w != self._width or h != self._height:
            return

        alpha = rgba[:, :, 3:4].astype(np.float32) * (1.0 / 255.0)
        fg = rgba[:, :, :3].astype(np.float32)
        bg = np.array(bg_color, dtype=np.float32)
        composited = fg * alpha + bg * (1.0 - alpha)
        np.clip(composited, 0, 255, out=composited)
        self._rgb_buf[:] = composited.astype(np.uint8)

        try:
            os.write(self._fd, self._rgb_buf.tobytes())
        except OSError as e:
            logger.warning("Virtual camera write failed: %s", e)
            self._status = f"Write error: {e}"
            self.close()

    def close(self) -> None:
        """Close the virtual camera device."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            self._rgb_buf = None
            self._status = "Closed"
            logger.info("Virtual camera closed")


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------

def is_v4l2loopback_loaded() -> bool:
    """Check if the v4l2loopback kernel module is loaded."""
    return os.path.isdir("/sys/module/v4l2loopback")


def find_v4l2loopback_devices(output_only: bool = True) -> list[str]:
    """Find v4l2loopback device paths.

    Args:
        output_only: If True, only return devices that support VIDEO_OUTPUT
                     (the writer side with exclusive_caps=1).
    """
    candidates = []
    sysfs = Path("/sys/class/video4linux")
    if not sysfs.exists():
        return candidates
    for entry in sorted(sysfs.iterdir()):
        name_file = entry / "name"
        if name_file.exists():
            try:
                name = name_file.read_text().strip().lower()
            except OSError:
                continue
            if "v4l2 loopback" in name or "dummy video" in name or "nixchirp" in name:
                dev_path = f"/dev/{entry.name}"
                if os.path.exists(dev_path):
                    candidates.append(dev_path)

    if not output_only or not candidates:
        return candidates

    # Filter for output-capable devices using QUERYCAP
    output_devs = []
    for dev in candidates:
        try:
            fd = os.open(dev, os.O_RDWR)
            try:
                cap = _v4l2_capability()
                fcntl.ioctl(fd, VIDIOC_QUERYCAP, cap)
                if cap.device_caps & V4L2_CAP_VIDEO_OUTPUT:
                    output_devs.append(dev)
            finally:
                os.close(fd)
        except OSError:
            continue

    return output_devs if output_devs else candidates


def load_v4l2loopback() -> tuple[bool, str]:
    """Attempt to load v4l2loopback via pkexec (graphical sudo).

    Loads with exclusive_caps=1 so the device properly supports
    VIDEO_OUTPUT (required for writing frames).

    Returns (success, message).
    """
    if is_v4l2loopback_loaded():
        # Reload with correct options if already loaded without exclusive_caps
        try:
            result = subprocess.run(
                ["pkexec", "sh", "-c",
                 "modprobe -r v4l2loopback && "
                 "modprobe v4l2loopback exclusive_caps=1 card_label=NixChirp"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                logger.info("v4l2loopback reloaded with exclusive_caps=1")
                return True, "Module loaded"
            elif result.returncode == 126:
                return False, "Authentication cancelled"
            else:
                msg = result.stderr.strip() or f"reload failed (code {result.returncode})"
                logger.warning("v4l2loopback reload failed: %s", msg)
                return False, msg
        except FileNotFoundError:
            return False, "pkexec not found"
        except subprocess.TimeoutExpired:
            return False, "Timed out"
        except OSError as e:
            return False, str(e)

    try:
        result = subprocess.run(
            ["pkexec", "modprobe", "v4l2loopback",
             "exclusive_caps=1", "card_label=NixChirp"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            logger.info("v4l2loopback loaded via pkexec")
            return True, "Module loaded"
        elif result.returncode == 126:
            return False, "Authentication cancelled"
        else:
            msg = result.stderr.strip() or f"modprobe failed (code {result.returncode})"
            logger.warning("modprobe v4l2loopback failed: %s", msg)
            return False, msg
    except FileNotFoundError:
        return False, "pkexec not found"
    except subprocess.TimeoutExpired:
        return False, "Timed out"
    except OSError as e:
        return False, str(e)
