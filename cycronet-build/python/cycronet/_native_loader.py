"""
Native library loader for platform-specific Cronet libraries.

This module handles the loading of Cronet DLL/SO/dylib and dependencies
before importing the Rust extension module.
"""

import os
import sys
import glob
import ctypes
import warnings


def load_native_libraries():
    """Load platform-specific native libraries."""

    # macOS dylib loading - preload libcronet.dylib
    if sys.platform == "darwin":
        _load_macos_libraries()

    # Linux SO loading - preload all dependency SO files
    elif sys.platform == "linux":
        _load_linux_libraries()

    # Windows DLL loading
    elif sys.platform == "win32":
        _load_windows_libraries()


def _load_macos_libraries():
    """Load macOS dylib libraries."""
    package_dir = os.path.dirname(__file__)
    dylib_pattern = os.path.join(package_dir, "libcronet.*.dylib")
    dylib_files = glob.glob(dylib_pattern)

    if dylib_files:
        try:
            # RTLD_GLOBAL makes the library visible to subsequently loaded modules
            ctypes.CDLL(dylib_files[0], mode=ctypes.RTLD_GLOBAL)
        except Exception as e:
            # If it fails, try setting DYLD_LIBRARY_PATH (requires process restart)
            warnings.warn(
                f"Failed to preload libcronet.dylib: {e}. "
                f"You may need to set DYLD_LIBRARY_PATH={package_dir}",
                RuntimeWarning
            )


def _load_linux_libraries():
    """Load Linux SO libraries in the correct order."""
    package_dir = os.path.dirname(__file__)

    # Silence GLib's "Using the 'memory' GSettings backend" message that Cronet's
    # system proxy-config service emits on headless Linux (no dconf). Cycronet sets
    # proxies explicitly and never uses system GSettings, so forcing the memory
    # backend is safe. setdefault respects any user-provided override.
    os.environ.setdefault("GSETTINGS_BACKEND", "memory")

    # Loading order is important: load base dependencies first, then NSS, finally cronet.
    # Cronet also needs GLib/GObject on Linux; preload the bundled copies so minimal
    # images do not need distro packages installed.
    for lib_name in [
        'libpcre.so.1',
        'libffi.so.6',
        'libglib-2.0.so.0',
        'libgobject-2.0.so.0',
    ]:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 1. Load NSPR (NSS base dependency)
    for lib_name in ['libnspr4.so', 'libplc4.so', 'libplds4.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 2. Load NSS utility libraries
    for lib_name in ['libnssutil3.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 3. Load NSS crypto libraries
    for lib_name in ['libfreebl3.so', 'libfreeblpriv3.so', 'libsoftokn3.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 4. Load NSS main libraries
    for lib_name in ['libnss3.so', 'libnssdbm3.so']:
        lib_path = os.path.join(package_dir, lib_name)
        if os.path.exists(lib_path):
            try:
                ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            except Exception:
                pass

    # 5. Finally load libcronet.so
    # Use RTLD_LOCAL to avoid symbol conflicts with other libraries (e.g. curl_cffi's BoringSSL).
    # The Rust extension module has DT_NEEDED + RPATH=$ORIGIN, so it resolves libcronet symbols
    # through ELF dependency, not the global symbol table.
    #
    # The .so is shipped as .so.pkg to prevent maturin from ignoring it during wheel build.
    # Rename .so.pkg -> .so on first load if needed.
    pkg_pattern = os.path.join(package_dir, "libcronet.*.so.pkg")
    pkg_files = glob.glob(pkg_pattern)
    for pkg_file in pkg_files:
        so_file = pkg_file[:-4]  # strip ".pkg"
        if not os.path.exists(so_file):
            try:
                os.rename(pkg_file, so_file)
            except Exception:
                try:
                    import shutil
                    shutil.copy2(pkg_file, so_file)
                except Exception:
                    pass

    so_pattern = os.path.join(package_dir, "libcronet.*.so")
    so_files = [f for f in glob.glob(so_pattern) if not f.endswith('.pkg')]
    if so_files:
        try:
            ctypes.CDLL(so_files[0], mode=ctypes.RTLD_LOCAL)
        except Exception:
            pass


def _load_windows_libraries():
    """Load Windows DLL libraries."""
    package_dir = os.path.dirname(__file__)

    # Find cronet.*.dll file
    dll_pattern = os.path.join(package_dir, "cronet.*.dll")
    dll_files = glob.glob(dll_pattern)

    if dll_files:
        # Use versioned DLL (cronet.144.0.7506.0.dll)
        versioned_dll = dll_files[0]

        # Add package directory to PATH (must be before add_dll_directory)
        os.environ['PATH'] = package_dir + os.pathsep + os.environ.get('PATH', '')

        # Add package directory to DLL search path
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(package_dir)

        # Preload DLL (Python 3.8+ requires explicit loading)
        try:
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008

            handle = kernel32.LoadLibraryExW(
                versioned_dll,
                None,
                LOAD_WITH_ALTERED_SEARCH_PATH
            )

            if not handle:
                ctypes.CDLL(versioned_dll)
        except Exception as e:
            warnings.warn(
                f"Failed to preload {os.path.basename(versioned_dll)}: {e}",
                RuntimeWarning
            )
    else:
        # Fallback to old cronet-bin path search
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "cronet-bin"),  # in package
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "cronet-bin"),  # site-packages/cronet-bin
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "cronet-bin"),  # parent level
            os.path.join(os.getcwd(), "cronet-bin"),  # current directory
        ]

        dll_loaded = False
        for path in possible_paths:
            dll_path = os.path.join(path, "cronet.dll")
            if os.path.exists(dll_path):
                if hasattr(os, 'add_dll_directory'):
                    os.add_dll_directory(path)
                else:
                    os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
                dll_loaded = False
                break

        if not dll_loaded:
            # Try loading from environment variable or system path
            pass
