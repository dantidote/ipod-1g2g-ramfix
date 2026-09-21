"""One checked operation at a time. Never formats or repartitions a device."""
from pathlib import Path

from . import core, devices


def execute(request, event=lambda message: None):
    action = request["action"]
    if action == "scan":
        return {"devices": devices.scan()}
    core.require(action in ("check", "install", "restore", "eject"), "Unknown operation")
    device = devices.selected(request["device_id"], request["identity"])
    identity = device["identity"]
    if action == "eject":
        devices.eject(device)
        return {"message": "The iPod was safely ejected. You can unplug it."}
    event("Reading the iPod's firmware")
    with devices.RawDisk(device) as disk:
        devices.selected(device["id"], identity)
        current = core.read_prefix(disk, identity["size"])
    if action == "check":
        _, version = core.inspect(current, identity["size"])
        return {"state": version, "prefix_sha256": core.sha(current),
                "message": "Compatible firmware found: " + version}
    folder = Path(request["backup_folder"]).resolve(strict=True)
    devices.backup_location(folder, device)
    if action == "install":
        core.require(core.sha(current) == request["checked_sha256"],
                     "The firmware changed after checking. Check compatibility again.")
        target = core.patched_prefix(current, identity["size"], request["version"])
        core.require(target != current, "This patch is already installed; no changes needed.")
        before = current
        allowed = core.changed_sectors(before, target)
    else:
        before, patched = core.load_backup(folder, identity)
        allowed = core.restore_source(current, before, patched)
        target = before
        if target == current:
            return {"message": "The backup's firmware is already installed. Nothing changed."}
    event("Closing access to the iPod's music volume")
    with devices.exclusive(device):
        # Recheck after locking/unmounting: selection and a prior read never
        # authorize writing to a different disk that later reuses its number.
        devices.selected(device["id"], identity)
        with devices.RawDisk(device) as disk:
            core.require(core.read_prefix(disk, identity["size"]) == current,
                         "Firmware changed while preparing; nothing written")
        if action == "install":
            event("Saving and verifying your firmware backup")
            saved_target = core.save_backup(folder, identity, before, request["version"])
            loaded_before, loaded_after = core.load_backup(folder, identity)
            core.require(loaded_before == current and loaded_after == target == saved_target,
                         "Backup verification failed; nothing written")
        devices.selected(device["id"], identity)
        with devices.RawDisk(device, writable=True, allowed=allowed) as disk:
            devices.selected(device["id"], identity)
            result = core.transaction(disk, current, target, identity["size"], allowed, event)
        event("Reopening the iPod to verify the complete firmware region")
        with devices.RawDisk(device) as disk:
            devices.selected(device["id"], identity)
            core.require(core.read_prefix(disk, identity["size"]) == target,
                         "Reopened-device verification failed. Keep your backup; recovery may be needed.")
    result["message"] = ("Installation verified." if action == "install" else "Backup restored and verified.")
    result["message"] += " Use Eject iPod, then restart it. Keep your backup folder."
    return result
