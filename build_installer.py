"""Build one Windows EXE or one Mac app, with all support files embedded."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

from installer import VERSION


def smoke_test(root, executable, launcher=False):
    for option, filename in (("--self-test", "package-import-test.json"),
                              ("--ui-smoke-test", "package-ui-test.json")):
        result = root / "build" / filename
        for path in (result, Path(str(result) + ".launcher.json"), Path(str(result) + ".launcher-error.txt")):
            if path.exists():
                path.unlink()
        try:
            subprocess.run([str(executable), option, "--result", str(result)], check=True, timeout=120)
        except Exception:
            error = Path(str(result) + ".launcher-error.txt")
            if error.exists():
                print(error.read_text(encoding="utf-8-sig"), file=sys.stderr)
            raise
        value = json.loads(result.read_text())
        if value.get("device_access") is not False or value.get("install_disabled_without_check") is False:
            raise SystemExit("Packaged smoke test failed")
        if launcher:
            checks = json.loads(Path(str(result) + ".launcher.json").read_text(encoding="utf-8-sig"))
            if not all(checks[key] for key in ("payload_hash_verified", "extracted_acl_verified",
                                              "temporary_folder_removed")):
                raise SystemExit("Single-file launcher checks failed")
            # CI runs elevated: exercise the protected extraction path.
            if os.environ.get("GITHUB_ACTIONS") and not checks["elevated"]:
                raise SystemExit("The protected Windows launcher path was not exercised")


def windows_exe(root, bundle, output):
    payload = root / "build/app-payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, "app/" + path.relative_to(bundle).as_posix())
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    template = (root / "packaging/WindowsLauncher.cs").read_text()
    source = root / "build/WindowsLauncher.cs"
    source.write_text(template.replace("@PAYLOAD_SHA256@", digest))
    framework = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319"
    subprocess.run([str(framework / "csc.exe"), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                    "/out:" + str(output), "/reference:" + str(framework / "System.IO.Compression.dll"),
                    "/reference:" + str(framework / "System.Windows.Forms.dll"),
                    "/resource:" + str(payload) + ",app.zip", str(source)], check=True)


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
    build = root / "build"
    build.mkdir(exist_ok=True)
    import tkinter
    import PyInstaller
    provenance = {"installer_version": VERSION, "source_commit": os.environ.get("GITHUB_SHA"),
                  "python_version": platform.python_version(), "architecture": machine,
                  "tcl_version": tkinter.Tcl().eval("info patchlevel"),
                  "pyinstaller_version": PyInstaller.__version__, "hardware_tested": False,
                  "format": "single-executable" if sys.platform == "win32" else "single-app-bundle"}
    info = build / "BUILD-INFO.json"
    info.write_text(json.dumps(provenance, indent=2) + "\n")
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", "iPod-RAM-Fix", "--distpath", "build/native",
            "--workpath", "build/pyinstaller", "--specpath", "build", "install_ipod.py"]
    for source, target in [(root / n, "docs") for n in ("LICENSE", "NOTICE.md", "INSTALLER.md")] + [
            (root / "third_party_licenses", "docs/third_party_licenses"), (info, "docs")]:
        args += ["--add-data", str(source) + os.pathsep + target]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "io.github.dantidote.ipod-ramfix"]
    subprocess.run(args, cwd=root, check=True)
    exports = build / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    name = "iPod-RAM-Fix-" + VERSION + "-" + label
    if sys.platform == "win32":
        target = exports / (name + ".exe")
        windows_exe(root, build / "native/iPod-RAM-Fix", target)
        smoke_test(root, target, launcher=True)
    else:
        bundle = build / "native/iPod-RAM-Fix.app"
        smoke_test(root, bundle / "Contents/MacOS/iPod-RAM-Fix")
        target = exports / (name + ".zip")
        # One Finder-visible item; instructions and licenses are inside the app.
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(bundle), str(target)], check=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    Path(str(target) + ".sha256").write_text(digest + "  " + target.name + "\n")
    print(json.dumps({"download": str(target), "sha256": digest, "signed": False}))


if __name__ == "__main__":
    main()
