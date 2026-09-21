# iPod RAM Fix — desktop installer preview

A local Windows/macOS app that checks your iPod, backs up its firmware, applies
the RAM fix, and verifies the result. No Apple firmware or personal device data
is included in the download. There is no firmware downloader.

**Preview status:** the patch has been used on one physical iPod. The earlier
device-specific Windows writer was used for that trial. This new general
installer is tested using synthetic disks and private firmware backups; its
complete Windows and Mac device workflows still need hardware validation.
The native apps are unsigned and are not Apple-notarized.

## Supported devices

**Requires stock Apple firmware 1.5. Rockbox does not need this fix.** The patch
addresses a memory leak in Apple's firmware. Rockbox installations and other
custom bootloaders are not supported, even if you can still boot into Apple's
menus. Only return to unmodified Apple firmware if you intend to use and patch
Apple's firmware. A failed firmware or checksum check can also mean a different
firmware version or damaged firmware; it does not by itself prove that Rockbox
is installed.

- First- and second-generation FireWire iPods, with the exact supported Apple
  software 1.5 payload. Full hashes are checked before modification.
- Windows-formatted **MBR/FAT32** disks with the installed firmware layout the
  installer recognizes. These can be patched from Windows or macOS.
- A working FireWire connection, including operating-system driver support.
  A USB cable or ordinary USB card reader does not qualify.
- 512-byte disk sectors. Other layouts and modified firmware are refused.

Mac-formatted Apple Partition Map/HFS+ iPods, third-generation and newer iPods,
Rockbox-modified firmware, and unrecognized layouts are not supported by this
preview. **Do not reformat your iPod to get around a compatibility refusal.**

Windows bundles target x64 Windows 10/11. Separate Mac bundles are built for
Intel and Apple silicon; the build tests run on macOS 15. Older macOS versions
are not comprehensively validated. Intel app startup and interface checks have
passed on High Sierra 10.13.6. Device discovery accepts High Sierra's single-root
registry output and its disk identity fields. An app running successfully does
not establish that a complete firmware installation will work on that computer.
Apple's built-in FireWire support requires **macOS Sequoia 15 or earlier**;
macOS Tahoe 26 and later cannot use this installer's FireWire connection.
See [Apple's port compatibility guidance](https://support.apple.com/en-us/109523).

## Install

1. On Windows, download the single `.exe`. No extra folders or setup are needed.
   On Mac, extract the ZIP to get one **iPod-RAM-Fix.app** and open it.
2. Connect the iPod using FireWire. Close iTunes, Music, Finder windows browsing
   the iPod, and other syncing applications. Keep a separate copy of your music.
3. Open **iPod-RAM-Fix.exe** on Windows or **iPod-RAM-Fix.app** on Mac.
   Windows requests administrator access at launch. Mac requests administrator
   access when checking or changing the device.
4. Choose **Find iPod**, select it by its displayed identity and capacity,
   then choose **Check iPod**. This reads firmware without writing it.
5. Choose **Back up and install** to apply the published **v1 memory-leak fix**.
   Select a folder on your computer and review the device before confirming.
   The app creates a new backup subfolder. There are no patch options to choose.
6. Keep power and FireWire connected. Wait for **Installation verified**.
7. Choose **Eject iPod**, then restart it. Check artists, albums, songs, playback,
   full-library shuffle, and reshuffle. Retain the complete backup folder.

The Windows executable contains the complete app. After administrator approval,
its launcher expands support files into a new protected temporary folder under
Program Files, runs the app, and removes that folder after normal exit. Only
Administrators and SYSTEM can access those elevated runtime files; individual
files and directories are also owned by Administrators. Backups must be saved
elsewhere, such as Documents, so cleanup cannot remove them. A crash or forced
shutdown can leave the temporary runtime folder behind.

The Mac app contains its supporting files inside the `.app` bundle. Instructions
and runtime notices are included in both versions under **More → Help & licenses**.

Only the firmware sectors containing the patch and its checksums are written.
The partition table and music partition are not written. The app locks or
unmounts music volumes during installation, writes and verifies each changed
sector, then verifies the complete firmware region again through a new handle.
On Mac, reads use one sector per transfer to accommodate early FireWire bridge
limitations. Checking, backup and verification can take several minutes.

Unsigned previews may be blocked by Windows SmartScreen or macOS Gatekeeper.
Verify the download source and checksum; use the operating system's per-app
approval if you choose to test it. Do not disable protection system-wide.
Signing/notarization is a separate release step and requires the maintainer's
signing credentials.

## Restore, including after an interrupted write

Keep `backup.json` and `firmware-before.bin` together. Open the app, find the
same iPod, choose **More → Restore backup**, and select `backup.json`. A compatibility
check is not required for restoration, because a partial write may have left
the firmware checksums invalid.

The app verifies device identity and backup contents, permits recovery only
within the sectors changed by that patch, and refuses changes elsewhere.
Restore returns to the firmware present when that backup was made. Backups
from earlier previews remain supported. For this preview, restore on the same
OS platform that made the backup.

If a write fails, the app attempts to restore the prior sectors immediately.
If it cannot verify recovery, keep the backup and reconnect the same iPod in
disk mode before using Restore backup. Do not run a formatting/restoration tool
first: changing the disk layout can prevent this backup from being restored
automatically. If disk mode cannot expose the disk, this app cannot recover it.

Backups contain Apple firmware and device identifiers. Keep them private and
do not attach them to public issues. They do not include your music.

## Build or run from source

Python 3.11 with Tk is used for packaged builds. From the project folder:

```sh
python install_ipod.py
```

The build uses PyInstaller and must run on the destination operating system.
The Windows build also uses the .NET Framework C# compiler supplied by Windows:

```sh
python -m pip install PyInstaller==6.16.0
python build_installer.py
```

The single Windows executable or Mac app ZIP and SHA-256 files appear in
`build/exports/`. The GitHub Actions workflow
builds Windows x64, Mac Intel, and Mac Apple silicon separately. It uploads
preview build artifacts, not a stable release. No firmware files enter the
workflow. The application does not contact GitHub or any other server at runtime.

## Validation

```sh
python -m unittest discover -s tests -v
python install_ipod.py --self-test
python install_ipod.py --ui-smoke-test
```

The tests exercise device-selection refusals, partition and firmware checks,
backup corruption/wrong-device rejection, stale selection, write confinement,
partial writes, failed readbacks, rollback, interrupted-write recovery, and
backup/volume-lock failures. Tests use invented data and mocked devices, never
native device APIs. Packaged executable checks open and close the interface
without scanning for or opening any disk.

The original file-only `patch_firmware.py` still builds v1 pre-install containers
and remains separate from this installed-device workflow.
