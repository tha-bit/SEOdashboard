from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build" / "offline-release"
DIST_ROOT = BUILD_ROOT / "dist"
WORK_ROOT = BUILD_ROOT / "work"
SPEC_ROOT = BUILD_ROOT / "spec"


def run(command: list[str]) -> None:
    environment = {**os.environ, "PYINSTALLER_CONFIG_DIR": str(BUILD_ROOT / "pyinstaller-cache")}
    subprocess.run(command, cwd=ROOT, check=True, env=environment)


def build_binary(platform_name: str) -> Path:
    separator = ";" if platform_name == "windows" else ":"
    name = "SEO Dashboard"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        name,
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(WORK_ROOT),
        "--specpath",
        str(SPEC_ROOT),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{ROOT / 'frontend' / 'dist'}{separator}frontend/dist",
        "--add-data",
        f"{ROOT / 'migrations'}{separator}migrations",
        "--add-data",
        f"{ROOT / 'alembic.ini'}{separator}.",
        "--collect-submodules",
        "uvicorn",
        str(ROOT / "packaging" / "seo_dashboard.py"),
    ]
    run(command)
    return DIST_ROOT / (f"{name}.app" if platform_name == "macos" else name)


def copy_readme(destination: Path, platform_name: str) -> None:
    source = ROOT / "packaging" / ("README-macOS.txt" if platform_name == "macos" else "README-Windows.txt")
    shutil.copy2(source, destination / "README.txt")


def sign_windows(executable: Path) -> None:
    certificate = os.getenv("WINDOWS_CERTIFICATE_PATH")
    password = os.getenv("WINDOWS_CERTIFICATE_PASSWORD")
    if not certificate or not password:
        return
    candidates = list(Path("C:/Program Files (x86)/Windows Kits/10/bin").glob("*/x64/signtool.exe"))
    signtool = shutil.which("signtool.exe") or (str(sorted(candidates)[-1]) if candidates else None)
    if not signtool:
        raise RuntimeError("Windows signing was requested but signtool.exe was not found")
    run([signtool, "sign", "/fd", "SHA256", "/f", certificate, "/p", password, "/tr", "http://timestamp.digicert.com", "/td", "SHA256", str(executable)])


def sign_and_notarize_macos(package: Path, asset: Path) -> None:
    identity = os.getenv("APPLE_SIGNING_IDENTITY")
    if identity:
        for app in (package / "Stop SEO Dashboard.app", package / "SEO Dashboard.app"):
            run(["codesign", "--deep", "--force", "--options", "runtime", "--timestamp", "--sign", identity, str(app)])
    apple_id, team_id, password = os.getenv("APPLE_ID"), os.getenv("APPLE_TEAM_ID"), os.getenv("APPLE_APP_PASSWORD")
    if not all((identity, apple_id, team_id, password)):
        return
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(package), str(asset)])
    run(["xcrun", "notarytool", "submit", str(asset), "--apple-id", apple_id, "--team-id", team_id, "--password", password, "--wait"])
    for app in (package / "SEO Dashboard.app", package / "Stop SEO Dashboard.app"):
        run(["xcrun", "stapler", "staple", str(app)])


def zip_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, path.relative_to(source.parent))
                with path.open("rb") as stream:
                    archive.writestr(info, stream.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def assemble_windows(binary: Path, output: Path, arch: str) -> Path:
    executable = binary / "SEO Dashboard.exe"
    sign_windows(executable)
    shutil.copy2(executable, binary / "Stop SEO Dashboard.exe")
    copy_readme(binary, "windows")
    asset = output / f"SEO-Data-Workspace-Windows-{arch}.zip"
    zip_tree(binary, asset)
    return asset


def assemble_macos(binary: Path, output: Path, arch: str) -> Path:
    package = BUILD_ROOT / "package" / "SEO Data Workspace"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    shutil.copytree(binary, package / binary.name, symlinks=True)
    stop_app = package / "Stop SEO Dashboard.app"
    shutil.copytree(ROOT / "packaging" / "macos" / "Stop SEO Dashboard.app", stop_app)
    (stop_app / "Contents" / "MacOS" / "stop-dashboard").chmod(0o755)
    copy_readme(package, "macos")
    asset = output / f"SEO-Data-Workspace-macOS-{arch}.zip"
    sign_and_notarize_macos(package, asset)
    asset.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(package), str(asset)])
    return asset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("windows", "macos"), required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "release-assets")
    args = parser.parse_args()
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    args.output.mkdir(parents=True, exist_ok=True)
    binary = build_binary(args.platform)
    asset = assemble_windows(binary, args.output, args.arch) if args.platform == "windows" else assemble_macos(binary, args.output, args.arch)
    print(asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
