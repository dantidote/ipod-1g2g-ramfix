"""Small native Windows/macOS backends; only identified FireWire iPods qualify."""
import ctypes
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from contextlib import contextmanager

from .core import MAX_PREFIX, SECTOR, require


def run(args):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(args, capture_output=True, timeout=90, **options)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise OSError(detail or "%s failed" % args[0])
    return result.stdout


def powershell(script):
    prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
    executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return json.loads(run([executable, "-NoProfile", "-NonInteractive", "-Command",
                           prefix + script]).decode("utf-8-sig"))


def mac_info(name):
    return plistlib.loads(run(["/usr/sbin/diskutil", "info", "-plist", name]))


def mac_guids(nodes, inherited=None):
    """Associate an IOMedia BSD name with its ancestor FireWire GUID."""
    result = {}
    for node in nodes:
        guid = node.get("GUID", inherited)
        if isinstance(guid, int) and guid > 0:
            if "BSD Name" in node:
                result[node["BSD Name"]] = "%016x" % guid
        result.update(mac_guids(node.get("IORegistryEntryChildren", []), guid))
    return result


def windows_candidates(rows):
    result = []
    for row in rows:
        if not (str(row.get("Bus")) in ("1394", "IEEE 1394") and
                re.search(r"\bipod\b", str(row.get("Name", "")), re.I) and
                not any(row.get(x, True) for x in ("Boot", "System", "Offline", "ReadOnly")) and
                row.get("Sector") == SECTOR and str(row.get("Serial", "")).strip() and
                row.get("Pnp")):
            continue
        identity = {"platform": "windows", "hardware_id": row["Serial"].strip(),
                    "model": row["Name"].strip(), "size": int(row["Size"]), "sector": SECTOR}
        result.append({"id": str(int(row["Number"])), "identity": identity,
                       "volumes": row.get("Volumes") or [], "pnp": row["Pnp"]})
    return result


def mac_candidate(info, guids, system_disks):
    name = info.get("DeviceIdentifier", "")
    model = info.get("MediaName") or info.get("IORegistryEntryName") or ""
    if not (re.fullmatch(r"disk\d+", name) and info.get("Whole") is True and
            info.get("Internal", info.get("DeviceInternal", True)) is False and
            info.get("BusProtocol") == "FireWire" and
            re.search(r"\bipod\b", model, re.I) and name in guids and name not in system_disks and
            info.get("DeviceBlockSize") == SECTOR and
            (info.get("Writable") is True or info.get("ReadOnlyMedia") is False)):
        return None
    return {"id": name, "identity": {"platform": "macos", "hardware_id": guids[name],
            "model": model, "size": int(info.get("TotalSize") or info.get("Size") or 0),
            "sector": SECTOR}}


def scan():
    if sys.platform == "win32":
        rows = powershell(r"""
$legacy = @(Get-CimInstance Win32_DiskDrive)
$rows = @(Get-Disk | ForEach-Object {
  $d = $_
  $w = $legacy | Where-Object Index -eq $d.Number
  $paths = @(Get-Partition -DiskNumber $d.Number | ForEach-Object { $_.AccessPaths })
  [PSCustomObject]@{Number=$d.Number; Name=$d.FriendlyName; Serial=$d.SerialNumber;
    Bus=[string]$d.BusType; Size=$d.Size; Sector=$d.LogicalSectorSize; Boot=$d.IsBoot;
    System=$d.IsSystem; Offline=$d.IsOffline; ReadOnly=$d.IsReadOnly;
    Volumes=$paths; Pnp=$w.PNPDeviceID}
})
ConvertTo-Json -InputObject $rows -Depth 5
""")
        return windows_candidates(rows)
    if sys.platform == "darwin":
        root = mac_info("/")  # Fail closed if the running system cannot be identified.
        system = {root.get("ParentWholeDisk"), root.get("DeviceIdentifier")}
        for item in root.get("APFSPhysicalStores", []):
            value = item.get("APFSPhysicalStore") if isinstance(item, dict) else item
            if value:
                system.add(re.sub(r"s\d+$", "", value))
        for name in list(system):
            if name and re.fullmatch(r"disk\d+", name):
                for item in mac_info(name).get("APFSPhysicalStores", []):
                    value = item.get("APFSPhysicalStore") if isinstance(item, dict) else item
                    if value:
                        system.add(re.sub(r"s\d+$", "", value))
        registry = plistlib.loads(run(["/usr/sbin/ioreg", "-a", "-l", "-p", "IOService"]))
        guids = mac_guids(registry)
        disks = plistlib.loads(run(["/usr/sbin/diskutil", "list", "-plist", "physical"]))
        result = []
        for name in disks.get("WholeDisks", []):
            candidate = mac_candidate(mac_info(name), guids, system)
            if candidate:
                result.append(candidate)
        return result
    raise OSError("The device installer supports Windows and macOS only.")


def selected(device_id, identity):
    matches = [d for d in scan() if d["id"] == device_id and d["identity"] == identity]
    require(len(matches) == 1, "The selected iPod disconnected or changed. Scan again.")
    require(sum(d["identity"] == identity for d in scan()) == 1,
            "Ambiguous device identity. Disconnect other iPods.")
    return matches[0]


def kernel():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, word, ptr = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p
    k.CreateFileW.argtypes = [ctypes.c_wchar_p, word, word, ptr, word, word, handle]
    k.CreateFileW.restype = handle
    k.CloseHandle.argtypes = [handle]
    k.SetFilePointerEx.argtypes = [handle, ctypes.c_longlong, ptr, word]
    k.ReadFile.argtypes = [handle, ptr, word, ctypes.POINTER(word), ptr]
    k.WriteFile.argtypes = [handle, ptr, word, ctypes.POINTER(word), ptr]
    k.FlushFileBuffers.argtypes = [handle]
    k.DeviceIoControl.argtypes = [handle, word, ptr, word, ptr, word, ctypes.POINTER(word), ptr]
    k.GetFinalPathNameByHandleW.argtypes = [handle, ctypes.c_wchar_p, word, word]
    return k


def open_windows(path, writable=False, directory=False):
    k = kernel()
    access = 0x80000000 | (0x40000000 if writable else 0)
    flags = 0x02000000 if directory else (0x80000000 if writable else 0)
    h = k.CreateFileW(path, access, 3, None, 3, flags, None)
    if h in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    return k, h


def ioctl(k, h, code):
    count = ctypes.c_uint32()
    if not k.DeviceIoControl(h, code, None, 0, None, 0, ctypes.byref(count), None):
        raise ctypes.WinError(ctypes.get_last_error())


def backup_location(folder, device):
    """The only usable rollback copy must not live on the iPod being patched."""
    if sys.platform == "win32":
        k, h = open_windows(str(folder), directory=True)
        try:
            buf = ctypes.create_unicode_buffer(32768)
            length = k.GetFinalPathNameByHandleW(h, buf, len(buf), 1)  # Volume GUID
            require(0 < length < len(buf) and buf.value.startswith("\\\\?\\Volume{"),
                    "Choose a backup folder on a local computer disk")
            volumes = [v for v in device["volumes"] if v and v.startswith("\\\\?\\Volume{")]
            require(volumes, "Cannot identify the iPod's volume; backup location check failed")
            require(not any(buf.value.lower().startswith(v.lower()) for v in volumes),
                    "Save the backup on your computer, not on the iPod")
        finally:
            k.CloseHandle(h)
    else:
        info = mac_info(str(folder))
        require(info.get("ParentWholeDisk") and info["ParentWholeDisk"] != device["id"],
                "Save the backup on your computer, not on the iPod")


@contextmanager
def exclusive(device):
    """Stop mounted filesystems accessing the selected device during the write."""
    if sys.platform == "win32":
        handles = []
        try:
            volumes = sorted({v.rstrip("\\") for v in device["volumes"]
                              if v and re.fullmatch(r"\\\\\?\\Volume\{[0-9a-fA-F-]+\}\\", v)})
            require(volumes, "No lockable iPod volume found; refusing to write")
            for path in volumes:
                k, h = open_windows(path, writable=True)
                handles.append((k, h))
                ioctl(k, h, 0x00090018)  # FSCTL_LOCK_VOLUME
                ioctl(k, h, 0x00090020)  # FSCTL_DISMOUNT_VOLUME
            yield
        finally:
            for k, h in reversed(handles):
                k.CloseHandle(h)  # Releases locks, including partially acquired ones.
    else:
        require(re.fullmatch(r"disk\d+", device["id"]), "Invalid disk identifier")
        run(["/usr/sbin/diskutil", "unmountDisk", "/dev/" + device["id"]])
        listing = plistlib.loads(run(["/usr/sbin/diskutil", "list", "-plist", device["id"]]))
        for node in listing.get("AllDisks", []):
            require(not mac_info(node).get("MountPoint"), "An iPod volume is still mounted")
        yield


class RawDisk:
    def __init__(self, device, writable=False, allowed=()):
        self.writable, self.allowed = writable, frozenset(allowed)
        self.closed = False
        self.windows = sys.platform == "win32"
        if self.windows:
            require(re.fullmatch(r"\d+", device["id"]), "Invalid disk identifier")
            self.k, self.h = open_windows(r"\\.\PhysicalDrive" + device["id"], writable)
        else:
            require(sys.platform == "darwin" and re.fullmatch(r"disk\d+", device["id"]),
                    "Invalid disk identifier")
            self.fd = os.open("/dev/r" + device["id"], os.O_RDWR if writable else os.O_RDONLY)

    def close(self):
        if not self.closed:
            if self.windows:
                self.k.CloseHandle(self.h)
            else:
                os.close(self.fd)
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def bounds(self, offset, length):
        require(not self.closed and offset >= 0 and length > 0 and
                offset % SECTOR == 0 and length % SECTOR == 0 and
                offset + length <= MAX_PREFIX, "Invalid firmware-region access")

    def seek(self, offset):
        if not self.k.SetFilePointerEx(self.h, offset, None, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self, offset, length):
        self.bounds(offset, length)
        if self.windows:
            self.seek(offset)
            buf, count = ctypes.create_string_buffer(length), ctypes.c_uint32()
            if not self.k.ReadFile(self.h, buf, length, ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            data = buf.raw[:count.value]
        else:
            data = os.pread(self.fd, length, offset)
        require(len(data) == length, "Short disk read")
        return data

    def write_sector(self, number, data):
        self.bounds(number * SECTOR, len(data))
        require(self.writable and number in self.allowed and len(data) == SECTOR,
                "Attempted write outside the approved patch sectors")
        if self.windows:
            self.seek(number * SECTOR)
            buf, count = ctypes.create_string_buffer(data), ctypes.c_uint32()
            if not self.k.WriteFile(self.h, buf, SECTOR, ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            require(count.value == SECTOR, "Short sector write")
            if not self.k.FlushFileBuffers(self.h):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            count = os.pwrite(self.fd, data, number * SECTOR)
            require(count == SECTOR, "Short sector write")
            os.fsync(self.fd)
        require(self.read(number * SECTOR, SECTOR) == data, "Sector readback mismatch")


def eject(device):
    selected(device["id"], device["identity"])
    if sys.platform == "darwin":
        run(["/usr/sbin/diskutil", "eject", "/dev/" + device["id"]])
    else:
        cfg = ctypes.WinDLL("cfgmgr32")
        cfg.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p,
                                          ctypes.c_uint32]
        cfg.CM_Request_Device_EjectW.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                                ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        node, veto = ctypes.c_uint32(), ctypes.c_uint32()
        message = ctypes.create_unicode_buffer(512)
        require(cfg.CM_Locate_DevNodeW(ctypes.byref(node), device["pnp"], 0) == 0,
                "Could not locate the iPod for ejection")
        result = cfg.CM_Request_Device_EjectW(node.value, ctypes.byref(veto), message, 512, 0)
        require(result == 0, "Windows could not eject the iPod: " + message.value +
                ". Close applications using it and use Windows Safely Remove Hardware.")
    for _ in range(10):
        if not any(d["identity"] == device["identity"] for d in scan()):
            return
        time.sleep(0.5)
    raise OSError("Ejection could not be verified. Use the system's eject command before unplugging.")
