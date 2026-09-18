"""Build native unsigned desktop bundles. Run on the destination OS."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from installer import VERSION


def main():
    root = Path(__file__).resolve().parent
    machine = platform.machine().lower()
    if sys.platform == "win32":
        label = "windows-x64"
        if machine not in ("amd64", "x86_64"):
            raise SystemExit("Build Windows x64 using x64 Python")
    elif sys.platform == "darwin":
        label = "macos-" + ("arm64" if machine == "arm64" else "intel")
    else:
        raise SystemExit("Build on Windows or macOS")
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=root, check=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", "iPod-RAM-Fix", "--distpath", "build/native",
            "--workpath", "build/pyinstaller", "--specpath", "build", "install_ipod.py"]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "io.github.dantidote.ipod-ramfix"]
    subprocess.run(args, cwd=root, check=True)
    suffix = ".app" if sys.platform == "darwin" else ""
    bundle = root / "build/native" / ("iPod-RAM-Fix" + suffix)
    executable = bundle / ("Contents/MacOS/iPod-RAM-Fix" if suffix else "iPod-RAM-Fix.exe")
    # Verify the packaged executable itself, with no device discovery or I/O.
    for option, filename in (("--self-test", "package-import-test.json"),
                              ("--ui-smoke-test", "package-ui-test.json")):
        result = root / "build" / filename
        if result.exists():
            result.unlink()
        subprocess.run([str(executable), option, "--result", str(result)], check=True, timeout=60)
        value = json.loads(result.read_text())
        if value.get("device_access") is not False or value.get("install_disabled_without_check") is False:
            raise SystemExit("Packaged smoke test failed")
    exports = root / "build/exports"
    exports.mkdir(parents=True, exist_ok=True)
    name = "iPod-RAM-Fix-" + VERSION + "-" + label
    stage = root / "build" / name
    stage.mkdir(exist_ok=False)
    shutil.copytree(bundle, stage / bundle.name, symlinks=True)
    for filename in ("LICENSE", "NOTICE.md", "INSTALLER.md"):
        shutil.copy2(root / filename, stage / filename)
    shutil.copytree(root / "third_party_licenses", stage / "third_party_licenses")
    import tkinter
    import PyInstaller
    interpreter = tkinter.Tcl()
    provenance = {"installer_version": VERSION, "source_commit": os.environ.get("GITHUB_SHA"),
                  "python_version": platform.python_version(), "architecture": machine,
                  "tcl_version": interpreter.eval("info patchlevel"),
                  "pyinstaller_version": PyInstaller.__version__,
                  "packaged_import_and_ui_checks": "passed", "hardware_tested": False}
    (stage / "BUILD-INFO.json").write_text(json.dumps(provenance, indent=2) + "\n")
    target = exports / (name + ".zip")
    if sys.platform == "darwin":
        # Preserve app framework symlinks and executable permissions.
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(stage), str(target)], check=True)
    else:
        shutil.make_archive(str(target.with_suffix("")), "zip", stage.parent, stage.name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n")
    print(json.dumps({"archive": str(target), "sha256": digest, "signed": False}))


if __name__ == "__main__":
    main()
