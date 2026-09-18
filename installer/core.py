"""Validated firmware transformations, backups and bounded write transactions.

This module has no device discovery or privileged operations. Disk access is
injected, permitting fault-injection tests without touching a physical disk.
"""
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

SECTOR = 512
MAX_PREFIX = 64 * 1024 * 1024
OSOS_OFFSET, OSOS_SIZE = 0x4400, 0x315AA8
HASHES = {
    "original": "98251add80f99732142532814c4ad5b95ee08ab844dd988458a6fa254e1c7c97",
    "v1": "4f5af3429b1292d214da55e808ef8120868f65abdfe54d27f02a189e04f42119",
    "v2": "da19b022e25e352879ba7e1a9ba2d0ce39507502b448748bc89a83c2366e42b4",
}
LEAK_FIX = bytes.fromhex("01402de9 000090e5 120000eb 0140bde8 100000ea")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def state(payload):
    digest = sha(payload)
    require(len(payload) == OSOS_SIZE and digest in HASHES.values(),
            "Unsupported or modified firmware. Nothing will be written.")
    return next(name for name, value in HASHES.items() if value == digest)


def immediate(value):
    for rot in range(16):
        for byte in range(256):
            bits = rot * 2
            decoded = ((byte >> bits) | (byte << (32 - bits))) & 0xFFFFFFFF if bits else byte
            if decoded == value:
                return (rot << 8) | byte
    raise ValueError("Unencodable ARM immediate")


def patch_payload(payload, version):
    before = state(payload)
    require(version in ("v1", "v2"), "Unknown patch version")
    require(not (before == "v2" and version == "v1"),
            "The newer v2 patch is already installed. Use your backup to restore.")
    if before == version:
        return payload
    result = bytearray(payload)
    if before == "original":
        result[0x34CA4:0x34CB8] = LEAK_FIX
        require(sha(result) == HASHES["v1"], "Memory-fix output hash mismatch")
    if version == "v2":
        for offset, value in ((0x33980, 4000), (0x3399C, 2000),
                              (0x339FC, 500), (0x33A14, 500), (0x33A64, 65536)):
            word = struct.unpack_from("<I", result, offset)[0]
            struct.pack_into("<I", result, offset, (word & ~0xFFF) | immediate(value))
        struct.pack_into("<i", result, 0x33B30, -4000)
        def bl(source, target):
            return 0xEB000000 | (((target - source - 8) // 4) & 0xFFFFFF)
        result[0x34DD4:0x34DF4] = struct.pack("<8I", 0xE1A00004,
            bl(0x34DD8, 0x34CBC), 0xE1A02000, 0xE1A00005,
            bl(0x34DE4, 0x34CBC), 0xE1520000, 0x81A02000, 0xE1A00005)
    require(sha(result) == HASHES[version], "Patched firmware hash mismatch")
    return bytes(result)


@dataclass(frozen=True)
class Layout:
    firmware_start: int
    firmware_size: int
    data_start: int
    data_size: int


def layout(mbr, disk_size):
    require(len(mbr) == SECTOR and mbr[510:512] == b"\x55\xaa",
            "This preview supports Windows-formatted (MBR/FAT32) iPods only. "
            "Mac-formatted Apple Partition Map disks are not yet supported.")
    entries = [mbr[446 + i * 16:462 + i * 16] for i in range(4)]
    require(entries[0][0] == 0 and entries[0][4] == 0 and
            entries[1][0] in (0, 0x80) and entries[1][4] in (0x0B, 0x0C) and
            not any(entries[2] + entries[3]), "Unsupported partition layout")
    fw, fw_count = struct.unpack_from("<II", entries[0], 8)
    data, data_count = struct.unpack_from("<II", entries[1], 8)
    require(fw > 0 and fw_count > 0 and data == fw + fw_count and data_count > 0,
            "Overlapping or unexpected partitions")
    require(0x4D5800 <= fw_count * SECTOR and data * SECTOR <= MAX_PREFIX and
            (data + data_count) * SECTOR <= disk_size, "Invalid partition bounds")
    return Layout(fw * SECTOR, fw_count * SECTOR, data * SECTOR, data_count * SECTOR)


def inspect(prefix, disk_size):
    part = layout(prefix[:SECTOR], disk_size)
    require(len(prefix) == part.data_start, "Incomplete firmware-region read")
    fw = part.firmware_start
    require(prefix[fw:fw + 4] == b"{{~~" and
            prefix[fw + 0x100:fw + 0x104] == b"]ih[" and
            struct.unpack_from("<I", prefix, fw + 0x104)[0] == 0x4000 and
            struct.unpack_from("<H", prefix, fw + 0x10A)[0] == 2,
            "Unsupported firmware container")
    payload = prefix[fw + OSOS_OFFSET:fw + OSOS_OFFSET + OSOS_SIZE]
    version = state(payload)
    checksum = sum(payload) & 0xFFFFFFFF
    # The staging directory uses absolute device offsets; the live directory
    # uses offsets relative to the firmware partition. Preserve both layouts.
    for directory, bias in ((0x4000, fw), (0x4200, 0)):
        entry = struct.unpack_from("<4s4s8I", prefix, fw + directory)
        require(entry == (b"!ATA", b"soso", 0, bias + OSOS_OFFSET, OSOS_SIZE,
                          0x28000000, 0, checksum, 0x130, 0xFFFFFFFF),
                "Unrecognized installed firmware directory or checksum")
        aupd = struct.unpack_from("<4s4s8I", prefix, fw + directory + 40)
        require(aupd[:6] == (b"!ATA", b"dpua", 1, bias + 0x31A000, 1816533, 0x28000000)
                and aupd[6:] == (0, 266112895, 0x130, 0x28000000),
                "Unsupported ROM-update directory")
    require(sum(prefix[fw + 0x31A000:fw + 0x31A000 + 1816533]) & 0xFFFFFFFF == 266112895,
            "ROM-update payload checksum mismatch")
    return part, version


def patched_prefix(prefix, disk_size, version):
    part, _ = inspect(prefix, disk_size)
    result = bytearray(prefix)
    start = part.firmware_start + OSOS_OFFSET
    payload = patch_payload(prefix[start:start + OSOS_SIZE], version)
    result[start:start + OSOS_SIZE] = payload
    for offset in (0x401C, 0x421C):
        struct.pack_into("<I", result, part.firmware_start + offset,
                         sum(payload) & 0xFFFFFFFF)
    inspect(result, disk_size)
    return bytes(result)


def changed_sectors(before, after):
    require(len(before) == len(after) and len(before) % SECTOR == 0, "Image size mismatch")
    return [i // SECTOR for i in range(0, len(before), SECTOR)
            if before[i:i + SECTOR] != after[i:i + SECTOR]]


def durable_new(path, data):
    # Never overwrite an existing backup or follow a pre-created file symlink.
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    require(Path(path).read_bytes() == data, "Backup readback failed")


def save_backup(folder, identity, before, version):
    folder = Path(folder)
    require(folder.is_dir() and not any(folder.iterdir()), "Choose a new, empty backup folder")
    after = patched_prefix(before, identity["size"], version)
    metadata = {"format": 1, "identity": identity, "target_version": version,
                "before_sha256": sha(before), "after_sha256": sha(after),
                "prefix_size": len(before)}
    durable_new(folder / "firmware-before.bin", before)
    durable_new(folder / "backup.json", (json.dumps(metadata, indent=2) + "\n").encode())
    # Persist the new directory entries, not just their file contents, on macOS.
    if os.name == "posix":
        for directory in (folder, folder.parent):
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    return after


def load_backup(folder, identity):
    folder = Path(folder)
    manifest = folder / "backup.json"
    require(manifest.is_file() and manifest.stat().st_size < 16384, "Invalid backup manifest")
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    require(meta.get("format") == 1 and meta.get("identity") == identity,
            "This backup belongs to a different device or computer platform")
    path = folder / "firmware-before.bin"
    require(path.is_file() and SECTOR <= path.stat().st_size <= MAX_PREFIX,
            "Invalid backup size")
    before = path.read_bytes()
    require(len(before) == meta.get("prefix_size") and sha(before) == meta.get("before_sha256"),
            "Backup is incomplete or damaged")
    after = patched_prefix(before, identity["size"], meta["target_version"])
    require(sha(after) == meta.get("after_sha256"), "Backup target hash mismatch")
    return before, after


def restore_source(current, before, after):
    require(len(current) == len(before), "Backup layout no longer matches")
    allowed = changed_sectors(before, after)
    # Permit interrupted/partial writes only inside sectors this patch owns.
    # The partition table and every other firmware sector must still match.
    require(all(current[i:i + SECTOR] == before[i:i + SECTOR]
                for i in range(0, len(before), SECTOR) if i // SECTOR not in allowed),
            "Device changed outside the patch sectors. Automatic restore refused.")
    return allowed


def read_prefix(disk, disk_size):
    mbr = disk.read(0, SECTOR)
    part = layout(mbr, disk_size)
    return b"".join(disk.read(offset, min(1024 * 1024, part.data_start - offset))
                    for offset in range(0, part.data_start, 1024 * 1024))


class TransactionError(RuntimeError):
    def __init__(self, message, restored):
        super().__init__(message)
        self.restored = restored


def transaction(disk, source, target, disk_size, allowed, event=lambda text: None):
    part = layout(source[:SECTOR], disk_size)
    changed = changed_sectors(source, target)
    require(set(changed) <= set(allowed) and
            all(part.firmware_start <= n * SECTOR < part.data_start for n in allowed),
            "Write would fall outside the approved firmware sectors")
    require(read_prefix(disk, disk_size) == source, "Device changed since checking; nothing written")
    # Code first, directory checksums last. Hardware power loss still requires
    # restoring from the durable backup; this is not an atomic flash operation.
    directories = {(part.firmware_start + x) // SECTOR for x in (0x4000, 0x4200)}
    order = sorted(changed, key=lambda n: (n in directories, n))
    attempted = []
    try:
        for number in order:
            event("Writing firmware sector %d" % number)
            attempted.append(number)
            disk.write_sector(number, target[number * SECTOR:(number + 1) * SECTOR])
        require(read_prefix(disk, disk_size) == target, "Full firmware readback differs")
    except Exception as error:
        for number in reversed(attempted):
            try:
                disk.write_sector(number, source[number * SECTOR:(number + 1) * SECTOR])
            except Exception:
                pass
        try:
            restored = read_prefix(disk, disk_size) == source
        except Exception:
            restored = False
        raise TransactionError("Write failed. " + ("Previous state restored and verified."
            if restored else "Recovery required: keep the backup and use Restore backup.")
            + " Details: " + str(error), restored) from error
    return {"sectors_written": len(order), "full_region_verified": True,
            "prefix_sha256": sha(target)}
