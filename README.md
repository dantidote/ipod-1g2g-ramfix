# iPod 1.5 RAM fix — experimental patch

A small patch for a reproducible memory leak in `iPod_1.1.5_2005_02_18`, the family-1 package for first- and second-generation FireWire iPods running Apple software 1.5.

Project: [dantidote/ipod-1g2g-ramfix](https://github.com/dantidote/ipod-1g2g-ramfix). Download the [experimental release](https://github.com/dantidote/ipod-1g2g-ramfix/releases/tag/v1.0.0-alpha.1).

**This distribution contains patching code, tests, and research notes. It does not contain an original or modified Apple firmware image.** The file-only patcher requires your own matching firmware file from a source you are authorized to use. The new desktop installer reads firmware from your own iPod. Neither tool downloads firmware.

## Desktop installer preview

An experimental desktop installer is available in this branch for **Windows x64, Mac Intel, and Mac Apple silicon**. It checks compatibility, saves a verified firmware backup, applies v1 or the experimental v2 patch, verifies the complete firmware region, and supports restoring that same iPod's backup. See [installation and recovery instructions](INSTALLER.md).

Windows is distributed as **one self-contained `.exe`**. Mac downloads contain
one `.app` bundle. Help and license notices are embedded; no separate support
folder needs to be kept alongside the download.
The interface guides you through connecting, checking compatibility, and
installing, with visible patch choices and a separate verification status area.

This preview accepts recognizable **first/second-generation FireWire iPods with a Windows-formatted MBR/FAT32 disk**. Mac-formatted Apple Partition Map disks and other firmware are refused. Its new general device workflows still need end-to-end hardware validation; the successful physical trial below used the earlier device-specific Windows writer. Build artifacts are unsigned previews, not a stable installer release. The existing `v1.0.0-alpha.1` release remains the file-only source package.

## Results so far

- **Emulation:** a pool of 9,000 synthetic 20-character titles used 14.28 MiB before the patch and 0.42 MiB afterward. Every title was preserved; patched cleanup returned all pool allocations. These are isolated string-pool measurements, not total device RAM.
- **Additional emulation:** three cycles of 20,000 variable-length Unicode titles; shared metadata; allocation failures; array and resource ownership tests.
- **One physical iPod:** the owner reported successful boot, artist/song/album browsing, music playback, and shuffling and reshuffling a 13,000-song library. Boot and the initial full-library shuffle were slow. No extended stability or on-device memory measurements have been collected.

This is an experimental release for an exact firmware image. It does not establish universal model compatibility, a supported song-count limit, or a fix for startup/shuffle speed.

## Requirements

- Python 3.8 or later. The patcher uses the standard library only.
- Your own copy of the matching **pre-install firmware container**, raw or gzip-compressed.
- Exact uncompressed SHA-256:

```text
af3950c2253dfd0a9f743440f01634ddb8ce018115c05d9ca0e675912202a3df
```

The uncompressed file is 5,068,800 bytes. A version label alone is insufficient: installed-device dumps, different container layouts, and other firmware versions are rejected. The package name `1.1.5` does not mean iPod touch software 1.1.5.

## Build a patched file locally

From this folder, after obtaining your own matching original:

```sh
python patch_firmware.py verify original.bin.gz
python patch_firmware.py apply original.bin.gz patched.bin.gz
python patch_firmware.py verify patched.bin.gz
```

The patcher verifies the complete input hash before applying fixed offsets and verifies the complete output hash afterward. It leaves the input untouched and refuses to overwrite an existing output. The resulting uncompressed SHA-256 must be:

```text
59b584ecffbbc802315ed506cd75bba130ec9797d6aa6c6379d80c335cc6300e
```

Only five replacement ARM instructions are included in the patcher. It retains the original null-handle checks from your input and updates both OSOS directory checksums. Across the complete firmware image, 19 bytes change.

To produce an original file again, supply your retained original as the reversal reference:

```sh
python patch_firmware.py revert patched.bin.gz restored.bin --original original.bin.gz
```

The public patcher does not embed the original routine's instruction bytes. Reversal therefore requires your original file. This only creates a local file; it does not roll back a device installation.

## Installing a file-only patcher's output

The generated file retains the source container's **pre-install** directory state. It must be processed by an installer that understands the exact device and firmware layout. It is not a whole-disk image and must not be copied raw onto an iPod or its firmware partition.

Flashpod's file loader accepted this generated image in testing and performed the normal install-state fixups. Its full flashing operation also formats/repartitions a drive; loader acceptance is not an in-place installation procedure. See its [loader implementation](https://github.com/davidbarnhart/flashpod/blob/main/flashpod/ipod_flash.py).

The physical trial used a separate, device-specific procedure: it backed up the firmware region, verified that the installed OS matched byte-for-byte, changed the routine and both checksums in place, preserved the installed directory state and music partition, and verified the full firmware region afterward. That machine-specific installer and its backups are intentionally excluded from this release. Do not reuse another person's physical disk number, sector offsets, or backup image.

## Reproduce the tests

After building a patched file locally:

```sh
python -m pip install unicorn==2.1.4
python test_firmware.py original.bin.gz patched.bin.gz --json local-results.json
```

Optional: append `--flashpod-source /path/to/flashpod` to test that checkout's file-loading/validation functions. No flashing function is invoked.

The included `test-results.json` was produced using this public patcher. The harness executes the supplied ARM routines on a chosen 16 MiB heap, bypassing synchronization for a single-threaded test. It does not emulate a whole iPod boot or playback. Hardware observations are reported separately above.

## Package contents

| File | Purpose |
|---|---|
| `patch_firmware.py` | Offline builder, verifier, and reversal using a supplied original |
| `test_firmware.py` | Emulator regression tests; firmware must be supplied locally |
| `test-results.json` | Recorded emulator results; no library or device-identifying data |
| `RESEARCH.md` | Explanation of the leak and patch |
| `PUBLISHING.md` | Suggested sharing process and release description |
| `NOTICE.md` | Distribution boundaries and license scope |
| `LICENSE` | MIT license for this project's new code and documentation |
| `.gitignore` | Allowlist to help keep firmware and local backups out of Git |
| `SHA256SUMS` | Checksums of the public files |

## License

This project's new code and documentation are [MIT-licensed](LICENSE). Apple's firmware is not included or licensed by this project. Independent research; not affiliated with or endorsed by Apple. Read `NOTICE.md` before redistributing.
