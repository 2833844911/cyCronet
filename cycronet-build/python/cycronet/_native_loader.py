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

    # Loading order is important: load base dependencies first, then NSS, finally cronet
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
    so_pattern = os.path.join(package_dir, "libcronet.*.so")
    so_files = glob.glob(so_pattern)
    if so_files:
        try:
            ctypes.CDLL(so_files[0], mode=ctypes.RTLD_GLOBAL)
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
        # Note: PYD file directly depends on the versioned DLL name
        versioned_dll = dll_files[0]

        # Add package directory to PATH (must be before add_dll_directory)
        os.environ['PATH'] = package_dir + os.pathsep + os.environ.get('PATH', '')

        # Add package directory to DLL search path
        if hasattr(os, 'add_dll_directory'):
            os.add_dll_directory(package_dir)

        # Preload versioned DLL (Python 3.8+ requires explicit loading)
        try:
            # Use LoadLibraryEx with LOAD_WITH_ALTERED_SEARCH_PATH
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008

            # Load versioned DLL (PYD depends on this name)
            handle = kernel32.LoadLibraryExW(
                versioned_dll,
                None,
                LOAD_WITH_ALTERED_SEARCH_PATH
            )

            if not handle:
                # If LoadLibraryExW fails, try ctypes.CDLL as fallback
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
