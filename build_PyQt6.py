#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build script for the modern Windows standalone EXE (PyQt6) and shared build runner."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


def print_banner(text: str) -> None:
    print("\n" + "=" * 80)
    print(f" {text}")
    print("=" * 80 + "\n")


def resolve_python() -> str:
    """Resolve Python executable, preferring active venv or project .venv."""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix) or os.environ.get("CI"):
        return sys.executable

    for candidate in (Path(".venv") / "Scripts" / "python.exe", Path("venv") / "Scripts" / "python.exe"):
        if candidate.exists():
            print(f"[INFO] Using virtual environment Python: {candidate}")
            return str(candidate)

    print("[WARNING] Project .venv not found; using current Python interpreter.")
    return sys.executable


def _is_module_available(python_exe: str, module_name: str) -> bool:
    if os.path.normcase(os.path.abspath(python_exe)) == os.path.normcase(os.path.abspath(sys.executable)):
        return importlib.util.find_spec(module_name) is not None
    res = subprocess.run(
        [python_exe, "-c", f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module_name!r}) else 1)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


def check_dependencies(
    python_exe: str,
    qt_backend: str,
    install_missing: bool = False,
) -> None:
    """Verify required build and runtime packages are installed in target Python."""
    print_banner(f"1. Checking dependencies ({qt_backend})")
    print(f"[INFO] Python executable: {python_exe}")

    required = [
        ("PyInstaller", "pyinstaller"),
        ("PIL", "Pillow>=10.0.0"),
        (qt_backend, qt_backend),
        ("pydicom", "pydicom>=2.4.0"),
        ("numpy", "numpy>=1.20.0"),
        ("pylibjpeg", "pylibjpeg"),
        ("libjpeg", "pylibjpeg-libjpeg"),
        ("openjpeg", "pylibjpeg-openjpeg"),
    ]

    missing = []
    for mod_name, pkg_spec in required:
        if _is_module_available(python_exe, mod_name):
            print(f"[OK] {mod_name} is available.")
        else:
            print(f"[MISSING] {mod_name} ({pkg_spec})")
            missing.append(pkg_spec)

    if missing:
        if install_missing:
            for pkg_spec in missing:
                print(f"[INFO] Installing {pkg_spec}...")
                subprocess.check_call([python_exe, "-m", "pip", "install", pkg_spec])
        else:
            pkgs = " ".join(f'"{p}"' if any(c in p for c in "><=") else p for p in missing)
            raise RuntimeError(
                f"Missing required packages: {', '.join(missing)}.\n"
                f"Install them with: {python_exe} -m pip install {pkgs}\n"
                "Or run this script with --install-deps."
            )


def _find_runtime_dll(python_exe: str, dll_name: str) -> Optional[Path]:
    py_dir = Path(python_exe).resolve().parent
    base_dir = Path(sys.base_prefix)
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"

    for directory in (py_dir, base_dir, system32):
        candidate = directory / dll_name
        if candidate.exists():
            return candidate
    return None


def _collect_pydicom_submodules(python_exe: str) -> Sequence[str]:
    script = (
        "from PyInstaller.utils.hooks import collect_submodules; "
        "print('\\n'.join(collect_submodules('pydicom')))"
    )
    res = subprocess.run([python_exe, "-c", script], capture_output=True, text=True)
    if res.returncode != 0:
        return ["pydicom"]
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


EXCLUDED_QT_BINARIES: Tuple[str, ...] = (
    "opengl32sw.dll",
    "libglesv2.dll",
    "libegl.dll",
    "d3dcompiler_47.dll",
)


def _inject_spec_binary_exclusions(
    spec_path: Path,
    excluded_binaries: Iterable[str] = EXCLUDED_QT_BINARIES,
) -> None:
    """Filter unused Qt OpenGL/ANGLE binaries out of a generated PyInstaller .spec file."""
    excluded = tuple(sorted({name.lower() for name in excluded_binaries if name}))
    if not excluded:
        return

    content = spec_path.read_text(encoding="utf-8")
    filter_block = (
        f"_EXCLUDED_BINARY_NAMES = {excluded!r}\n"
        "a.binaries = [\n"
        "    item for item in a.binaries\n"
        "    if item[0].replace('\\\\', '/').rsplit('/', 1)[-1].lower() not in _EXCLUDED_BINARY_NAMES\n"
        "]\n\n"
    )
    marker = "pyz = PYZ("
    if marker not in content:
        raise RuntimeError(f"Expected marker {marker!r} not found in generated spec: {spec_path}")
    spec_path.write_text(content.replace(marker, filter_block + marker, 1), encoding="utf-8")


def run_pyinstaller_build(
    *,
    exe_name: str,
    qt_backend: str,
    exclude_qt: str,
    runtime_dlls: Tuple[str, ...],
    extra_hidden_imports: Iterable[str] = (),
    install_missing: bool = False,
) -> Path:
    """Run a clean PyInstaller one-file build for the specified Qt backend."""
    root_dir = Path(__file__).parent.resolve()
    os.chdir(root_dir)
    python_exe = resolve_python()
    check_dependencies(python_exe, qt_backend, install_missing=install_missing)

    print_banner(f"2. Compiling {exe_name}.exe ({qt_backend})")

    build_dir = root_dir / "build"
    if build_dir.exists():
        print(f"[INFO] Cleaning build directory: {build_dir}")
        shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    themes_dir = root_dir / "themes"
    locales_dir = root_dir / "locales"
    main_script = root_dir / "main.py"

    spec_args = [
        python_exe,
        "-m",
        "PyInstaller.utils.cliutils.makespec",
        "--onefile",
        "--windowed",
        "--noupx",
        f"--specpath={build_dir}",
        f"--paths={root_dir}",
        f"--add-data={themes_dir};themes",
        f"--add-data={locales_dir};locales",
        f"--name={exe_name}",
    ]

    icon_path = themes_dir / "app_icon.ico"
    if icon_path.exists():
        spec_args.append(f"--icon={icon_path}")
    else:
        print(f"[WARNING] Icon not found at {icon_path}; building with default icon.")

    for dll_name in runtime_dlls:
        dll_path = _find_runtime_dll(python_exe, dll_name)
        if dll_path:
            spec_args.append(f"--add-binary={dll_path};.")
            print(f"[INFO] Bundling runtime DLL: {dll_path}")
        else:
            print(f"[WARNING] Runtime DLL not found: {dll_name}")

    pydicom_subs = _collect_pydicom_submodules(python_exe)
    print(f"[INFO] Collected {len(pydicom_subs)} pydicom submodules.")
    for mod in pydicom_subs:
        spec_args.append(f"--hidden-import={mod}")

    for pkg in ("pylibjpeg", "libjpeg", "openjpeg"):
        spec_args.append(f"--collect-all={pkg}")

    for mod in ("unicodedata", "PIL", *extra_hidden_imports):
        spec_args.append(f"--hidden-import={mod}")

    for mod in (
        exclude_qt,
        f"{exclude_qt}.QtCore",
        f"{exclude_qt}.QtGui",
        f"{exclude_qt}.QtWidgets",
        f"{exclude_qt}.sip",
    ):
        spec_args.append(f"--exclude-module={mod}")

    spec_args.append(str(main_script))

    print(f"[INFO] Spec command:\n{' '.join(spec_args)}")
    subprocess.check_call(spec_args)

    spec_path = build_dir / f"{exe_name}.spec"
    _inject_spec_binary_exclusions(spec_path)
    print(f"[INFO] Patched {spec_path.name} to exclude unused Qt binaries: {', '.join(EXCLUDED_QT_BINARIES)}")

    build_args = [
        python_exe,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec_path),
    ]
    print(f"[INFO] Build command:\n{' '.join(build_args)}")
    subprocess.check_call(build_args)

    exe_path = Path("dist") / f"{exe_name}.exe"
    print_banner(f"BUILD COMPLETE: {exe_path}")
    return exe_path


def main() -> None:
    install_missing = "--install-deps" in sys.argv or bool(os.environ.get("CI"))
    try:
        run_pyinstaller_build(
            exe_name="DICOM_TPS_Harmonizer",
            qt_backend="PyQt6",
            exclude_qt="PyQt5",
            runtime_dlls=("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"),
            install_missing=install_missing,
        )
    except Exception as exc:
        print(f"\n[FATAL ERROR] PyQt6 build failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

