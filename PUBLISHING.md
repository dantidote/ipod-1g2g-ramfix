# Sharing this patch

## Public distribution

The project lives at [dantidote/ipod-1g2g-ramfix](https://github.com/dantidote/ipod-1g2g-ramfix). Share its [experimental release](https://github.com/dantidote/ipod-1g2g-ramfix/releases/tag/v1.0.0-alpha.1), which contains this source package. GitHub can host release notes and downloadable assets; see [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

1. Upload only the contents of this `ipod-ramfix-public` folder into a fresh repository. Do not upload the parent research workspace or its history.
2. Preserve the included MIT license and attribution when redistributing this project's code. This license grants no rights to Apple's firmware.
3. Mark the first release experimental and state that the firmware must be supplied separately by each recipient.
4. Attach the public ZIP and its SHA-256 checksum, or use GitHub's automatic source download.
5. Share the release link with a short explanation and ask testers for their exact model, library size, and observed results. Keep full serial numbers, personal databases, and firmware dumps out of public issue reports.

## Exclude from publication

- The earlier `ipod-ramfix-v1.zip`: it contains the patched Apple firmware.
- Any original or patched `.bin`, `.bin.gz`, `.ipsw`, `.img`, or disk image.
- Device backups, `iTunesDB`, preferences, SysInfo, serial numbers, and machine-specific install logs/scripts.
- The complete local workspace, which contains firmware downloads and personal backups.

The included `.gitignore` allows only the intended public filenames by default. It is a guard against accidentally adding new files, not a substitute for reviewing a release archive or already tracked files. If a firmware file was already committed to a repository, deleting the current copy does not remove it from older commits; publish from a fresh clean source folder.

## Suggested release description

> Experimental RAM-leak patch for the exact `iPod_1.1.5_2005_02_18` firmware container (Apple software 1.5, first/second-generation FireWire iPods).
>
> Fixes a handle-disposal routine that abandoned backing allocations during library-string-table growth. In isolated ARM emulation, a 9,000-title pool dropped from 14.28 MiB to 0.42 MiB. One physical-device tester reported successful browsing, playback, shuffle, and reshuffle with 13,000 songs; startup and shuffle remain slow.
>
> Patch source and tests only. No Apple firmware, personal library data, or universal device installer included. Supply your own authorized matching firmware file; the patcher verifies exact input/output hashes. Experimental, with limited hardware coverage.

## Legal scope

This packaging avoids distributing a complete original or modified firmware image. It is not a legal determination that every use or distribution of the patch is permitted. Firmware license terms, reverse-engineering rules, and local law may still matter. See `NOTICE.md` for the distinction between this code and the firmware it modifies.
