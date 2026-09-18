"""Firmware-free safety tests. No native device API is called."""
import contextlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from installer import core, devices, service


def fixture():
    # Synthetic bytes, not a copy or excerpt of Apple firmware. Production hash
    # allowlists are replaced only inside these test contexts.
    fw = 63 * 512
    end = fw + 6 * 1024 * 1024
    data_size = 8 * 1024 * 1024
    image = bytearray(end)
    image[510:512] = b"\x55\xaa"
    struct.pack_into("<II", image, 454, 63, (end - fw) // 512)
    image[466] = 0x0B
    struct.pack_into("<II", image, 470, end // 512, data_size // 512)
    image[fw:fw + 4] = b"{{~~"
    image[fw + 0x100:fw + 0x104] = b"]ih["
    struct.pack_into("<I", image, fw + 0x104, 0x4000)
    struct.pack_into("<H", image, fw + 0x10A, 2)
    payload = bytes([0x52]) * core.OSOS_SIZE
    image[fw + core.OSOS_OFFSET:fw + core.OSOS_OFFSET + core.OSOS_SIZE] = payload
    # A synthetic ROM-update payload with the expected additive checksum.
    aupd = bytes([255]) * (266112895 // 255) + bytes([266112895 % 255])
    image[fw + 0x31A000:fw + 0x31A000 + len(aupd)] = aupd
    for directory, bias in ((0x4000, fw), (0x4200, 0)):
        struct.pack_into("<4s4s8I", image, fw + directory, b"!ATA", b"soso", 0,
                         bias + core.OSOS_OFFSET, core.OSOS_SIZE, 0x28000000, 0,
                         sum(payload) & 0xFFFFFFFF, 0x130, 0xFFFFFFFF)
        struct.pack_into("<4s4s8I", image, fw + directory + 40, b"!ATA", b"dpua", 1,
                         bias + 0x31A000, 1816533, 0x28000000, 0, 266112895, 0x130, 0x28000000)
    v1 = bytearray(payload)
    v1[0x34CA4:0x34CB8] = core.LEAK_FIX
    return bytes(image), end + data_size, {"original": core.sha(payload), "v1": core.sha(v1),
                                          "v2": "not-used-by-synthetic-tests"}


class MemoryDisk:
    def __init__(self, prefix, fail_at=None, failure="partial"):
        self.data = bytearray(prefix + b"MUSIC" * 1024)
        self.fail_at, self.failure = fail_at, failure
        self.writes, self.calls = [], 0
        self.closed = False

    def read(self, offset, length):
        return bytes(self.data[offset:offset + length])

    def write_sector(self, number, data):
        self.calls += 1
        self.writes.append(number)
        offset = number * 512
        if self.failure == "persistent" and self.fail_at is not None and self.calls >= self.fail_at:
            if self.calls == self.fail_at:
                self.data[offset:offset + 256] = data[:256]
            raise OSError("Injected persistent write failure")
        if self.calls == self.fail_at:
            if self.failure == "partial":
                self.data[offset:offset + 256] = data[:256]
            elif self.failure == "readback":
                self.data[offset:offset + 512] = data
            raise OSError("Injected write/readback failure")
        self.data[offset:offset + 512] = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before, cls.size, cls.hashes = fixture()
        with patch.dict(core.HASHES, cls.hashes, clear=True):
            cls.after = core.patched_prefix(cls.before, cls.size, "v1")
        cls.allowed = core.changed_sectors(cls.before, cls.after)
        cls.identity = {"platform": "test", "hardware_id": "synthetic-device", "size": cls.size}

    def setUp(self):
        self.hasher = patch.dict(core.HASHES, self.hashes, clear=True)
        self.hasher.start()
        self.addCleanup(self.hasher.stop)


class CoreTests(FixtureCase):
    def test_production_allowlist_rejects_synthetic_firmware(self):
        self.hasher.stop()
        with self.assertRaisesRegex(ValueError, "Unsupported or modified"):
            core.inspect(self.before, self.size)

    def test_validated_layout_and_patch_preserve_mbr_and_unused_region(self):
        part, version = core.inspect(self.after, self.size)
        self.assertEqual(version, "v1")
        self.assertEqual(self.before[:part.firmware_start], self.after[:part.firmware_start])
        self.assertEqual(self.before[part.firmware_start + 0x31A000:],
                         self.after[part.firmware_start + 0x31A000:])
        self.assertEqual(len(self.allowed), 3)

    def test_reject_bad_layouts(self):
        for offset, value in ((510, 0), (450, 0xEE), (466, 7), (478, 1), (454, 0)):
            with self.subTest(offset=offset):
                data = bytearray(self.before)
                data[offset] = value
                with self.assertRaises(ValueError):
                    core.layout(data[:512], self.size)
        with self.assertRaises(ValueError):
            core.layout(self.before[:512], self.size - 512)

    def test_reject_overlapping_or_oversized_prefix(self):
        for count in (1, 200000):
            data = bytearray(self.before[:512])
            struct.pack_into("<I", data, 470, count)
            with self.assertRaises(ValueError):
                core.layout(data, self.size)

    def test_reject_changed_firmware_directory_and_payload(self):
        for offset in (63 * 512 + 0x401C, 63 * 512 + 0x420C,
                       63 * 512 + 0x4400 + 0x1000, 63 * 512 + 0x31A000):
            data = bytearray(self.before)
            data[offset] ^= 1
            with self.assertRaises(ValueError):
                core.inspect(data, self.size)

    def test_transaction_only_writes_patch_sectors_and_preserves_music(self):
        disk = MemoryDisk(self.before)
        music = bytes(disk.data[len(self.before):])
        result = core.transaction(disk, self.before, self.after, self.size, self.allowed)
        self.assertTrue(result["full_region_verified"])
        self.assertEqual(set(disk.writes), set(self.allowed))
        self.assertEqual(bytes(disk.data[:len(self.before)]), self.after)
        self.assertEqual(bytes(disk.data[len(self.before):]), music)

    def test_every_write_failure_rolls_back_in_both_directions(self):
        for source, target in ((self.before, self.after), (self.after, self.before)):
            for mode in ("partial", "readback", "before"):
                for at in range(1, len(self.allowed) + 1):
                    with self.subTest(direction=core.sha(source), mode=mode, at=at):
                        disk = MemoryDisk(source, at, mode)
                        with self.assertRaises(core.TransactionError) as caught:
                            core.transaction(disk, source, target, self.size, self.allowed)
                        self.assertTrue(caught.exception.restored)
                        self.assertEqual(bytes(disk.data[:len(source)]), source)

    def test_failed_rollback_is_reported_and_backup_can_recover(self):
        disk = MemoryDisk(self.before, 2, "persistent")
        with self.assertRaises(core.TransactionError) as caught:
            core.transaction(disk, self.before, self.after, self.size, self.allowed)
        self.assertFalse(caught.exception.restored)
        current = bytes(disk.data[:len(self.before)])
        allowed = core.restore_source(current, self.before, self.after)
        disk.fail_at = None
        core.transaction(disk, current, self.before, self.size, allowed)
        self.assertEqual(bytes(disk.data[:len(self.before)]), self.before)

    def test_stale_source_or_out_of_bounds_plan_never_writes(self):
        for source, allowed in ((self.after, self.allowed), (self.before, [0]),
                                 (self.before, self.allowed + [self.size // 512])):
            disk = MemoryDisk(self.before)
            with self.assertRaises(ValueError):
                core.transaction(disk, source, self.after, self.size, allowed)
            self.assertEqual(disk.writes, [])

    def test_restore_refuses_unrelated_changes(self):
        data = bytearray(self.after)
        data[2000] ^= 1
        with self.assertRaisesRegex(ValueError, "outside the patch"):
            core.restore_source(data, self.before, self.after)

    def test_backup_roundtrip_wrong_identity_corruption_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            core.save_backup(folder, self.identity, self.before, "v1")
            self.assertEqual(core.load_backup(folder, self.identity), (self.before, self.after))
            with self.assertRaises(ValueError):
                core.save_backup(folder, self.identity, self.before, "v1")
            with self.assertRaises(ValueError):
                core.load_backup(folder, dict(self.identity, hardware_id="other-device"))
            path = Path(folder) / "firmware-before.bin"
            with path.open("r+b") as stream:
                stream.write(b"BAD")
            with self.assertRaisesRegex(ValueError, "damaged"):
                core.load_backup(folder, self.identity)

    def test_unknown_version_and_wrong_target_hash_are_rejected(self):
        with self.assertRaises(ValueError):
            core.patched_prefix(self.before, self.size, "v3")
        with tempfile.TemporaryDirectory() as folder:
            core.save_backup(folder, self.identity, self.before, "v1")
            manifest = Path(folder) / "backup.json"
            meta = json.loads(manifest.read_text())
            meta["after_sha256"] = "0" * 64
            manifest.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, "target hash"):
                core.load_backup(folder, self.identity)


class SelectionTests(unittest.TestCase):
    def test_windows_never_offers_internal_system_or_unidentified_disks(self):
        row = dict(Number=2, Name="Apple iPod", Serial="test-guid", Bus="1394", Size=100000000,
                   Sector=512, Boot=False, System=False, Offline=False, ReadOnly=False,
                   Pnp="test-pnp", Volumes=[])
        self.assertEqual(len(devices.windows_candidates([row])), 1)
        for key, value in (("Bus", "SATA"), ("Boot", True), ("System", True),
                           ("ReadOnly", True), ("Offline", True), ("Serial", ""),
                           ("Sector", 4096), ("Name", "USB reader"), ("Pnp", ""), ("Boot", None)):
            self.assertEqual(devices.windows_candidates([dict(row, **{key: value})]), [])

    def test_mac_checks_guid_bus_writability_and_system_disk(self):
        info = dict(DeviceIdentifier="disk3", Whole=True, Internal=False, BusProtocol="FireWire",
                    DeviceBlockSize=512, Writable=True, MediaName="Apple iPod", TotalSize=100000000)
        guids = {"disk3": "fake-guid"}
        self.assertIsNotNone(devices.mac_candidate(info, guids, {"disk0"}))
        self.assertIsNone(devices.mac_candidate(info, guids, {"disk3"}))
        self.assertIsNone(devices.mac_candidate(info, {}, set()))
        for key, value in (("Internal", True), ("Whole", False), ("Writable", False),
                           ("BusProtocol", "USB"), ("DeviceBlockSize", 4096)):
            self.assertIsNone(devices.mac_candidate(dict(info, **{key: value}), guids, set()))

    def test_ioreg_guid_inheritance(self):
        tree = [{"GUID": 42, "IORegistryEntryChildren": [
            {"IORegistryEntryChildren": [{"BSD Name": "disk3"}]}]}]
        self.assertEqual(devices.mac_guids(tree), {"disk3": "000000000000002a"})

    def test_same_number_reused_for_different_device_is_rejected(self):
        with patch.object(devices, "scan", return_value=[{"id": "2", "identity": {"id": "new"}}]):
            with self.assertRaisesRegex(ValueError, "disconnected or changed"):
                devices.selected("2", {"id": "old"})


class NativeBoundaryTests(unittest.TestCase):
    def raw(self):
        disk = devices.RawDisk.__new__(devices.RawDisk)
        disk.windows, disk.closed, disk.writable = False, False, True
        disk.fd, disk.allowed = 123, frozenset({5})
        return disk

    def test_mac_reads_always_use_single_sector_syscalls(self):
        disk = self.raw()
        with patch.object(devices.os, "pread", create=True, return_value=b"a" * 512) as read:
            self.assertEqual(disk.read(1024, 1536), b"a" * 1536)
            self.assertEqual([c.args for c in read.call_args_list],
                             [(123, 512, 1024), (123, 512, 1536), (123, 512, 2048)])

    def test_mac_short_read_stops_immediately(self):
        with patch.object(devices.os, "pread", create=True, return_value=b"a" * 256) as read:
            with self.assertRaisesRegex(ValueError, "Short disk read"):
                self.raw().read(0, 1024)
            self.assertEqual(read.call_count, 1)

    def test_raw_write_guard_blocks_unapproved_or_unaligned_access(self):
        disk = self.raw()
        with patch.object(devices.os, "pwrite", create=True) as write:
            for number, data in ((0, b"a" * 512), (5, b"a" * 1024), (5, b"a" * 511)):
                with self.assertRaises(ValueError):
                    disk.write_sector(number, data)
            write.assert_not_called()

    def test_mac_sector_write_flushes_and_verifies(self):
        disk = self.raw()
        with patch.object(devices.os, "pwrite", create=True, return_value=512) as write, \
             patch.object(devices.os, "fsync") as flush, \
             patch.object(devices.os, "pread", create=True, return_value=b"b" * 512):
            disk.write_sector(5, b"b" * 512)
            write.assert_called_once_with(123, b"b" * 512, 2560)
            flush.assert_called_once_with(123)


class ServiceTests(FixtureCase):
    def service_context(self, disk, folder):
        stack = contextlib.ExitStack()
        device = {"id": "fake", "identity": self.identity}
        stack.enter_context(patch.object(devices, "selected", return_value=device))
        stack.enter_context(patch.object(devices, "RawDisk", return_value=disk))
        stack.enter_context(patch.object(devices, "exclusive", side_effect=lambda d: contextlib.nullcontext()))
        stack.enter_context(patch.object(devices, "backup_location"))
        return stack

    def request(self, folder, action="install"):
        return {"action": action, "device_id": "fake", "identity": self.identity,
                "backup_folder": folder, "version": "v1", "checked_sha256": core.sha(self.before)}

    def test_service_install_restore_and_reopened_verification(self):
        disk = MemoryDisk(self.before)
        with tempfile.TemporaryDirectory() as folder, self.service_context(disk, folder):
            result = service.execute(self.request(folder))
            self.assertTrue(result["full_region_verified"])
            self.assertTrue((Path(folder) / "backup.json").is_file())
            service.execute(self.request(folder, "restore"))
            self.assertEqual(bytes(disk.data[:len(self.before)]), self.before)

    def test_service_backup_failure_prevents_device_writes(self):
        disk = MemoryDisk(self.before)
        with tempfile.TemporaryDirectory() as folder, self.service_context(disk, folder), \
             patch.object(core, "save_backup", side_effect=OSError("Disk full")):
            with self.assertRaisesRegex(OSError, "Disk full"):
                service.execute(self.request(folder))
            self.assertEqual(disk.writes, [])

    def test_service_changed_after_check_prevents_writes_and_backup(self):
        disk = MemoryDisk(self.after)
        with tempfile.TemporaryDirectory() as folder, self.service_context(disk, folder):
            with self.assertRaisesRegex(ValueError, "changed after checking"):
                service.execute(self.request(folder))
            self.assertEqual(disk.writes, [])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_service_lock_failure_prevents_writes(self):
        disk = MemoryDisk(self.before)
        with tempfile.TemporaryDirectory() as folder, self.service_context(disk, folder), \
             patch.object(devices, "exclusive", side_effect=OSError("Volume busy")):
            with self.assertRaisesRegex(OSError, "Volume busy"):
                service.execute(self.request(folder))
            self.assertEqual(disk.writes, [])


if __name__ == "__main__":
    unittest.main()
