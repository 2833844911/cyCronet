use std::env;
use std::path::PathBuf;

fn main() {
    // 1. Generate Bindings for Cronet C API
    // Determine paths based on OS
    let dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let root = PathBuf::from(&dir).join("cronet-bin");

    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap();
    let (include_dir, lib_dir) = if target_os == "linux" {
        (root.join("linux").join("include"), root.join("linux"))
    } else if target_os == "macos" {
        (root.join("mac").join("include"), root.join("mac"))
    } else {
        (root.join("include"), root)
    };

    // 0. Export Cronet Version
    let version_path = lib_dir.join("VERSION");
    let version_content =
        std::fs::read_to_string(&version_path).expect("Failed to read VERSION file");

    // Parse VERSION file (format: MAJOR=x\nMINOR=y\nBUILD=z\nPATCH=w)
    let mut major = String::new();
    let mut minor = String::new();
    let mut build = String::new();
    let mut patch = String::new();
    for line in version_content.lines() {
        if let Some((key, value)) = line.split_once('=') {
            match key.trim() {
                "MAJOR" => major = value.trim().to_string(),
                "MINOR" => minor = value.trim().to_string(),
                "BUILD" => build = value.trim().to_string(),
                "PATCH" => patch = value.trim().to_string(),
                _ => {}
            }
        }
    }
    let version = format!("{}.{}.{}.{}", major, minor, build, patch);
    println!("cargo:rustc-env=CRONET_VERSION={}", version);
    println!("cargo:rerun-if-changed={}", version_path.display());

    // 1. Generate Bindings for Cronet C API
    let out_path = PathBuf::from(env::var("OUT_DIR").unwrap());
    let target = env::var("TARGET").unwrap();

    // For Linux and macOS targets, use pre-generated bindings to avoid bindgen dependency
    if target.contains("linux") {
        let pregenerated = PathBuf::from(&dir).join("src/cronet_bindings_linux.rs");
        if pregenerated.exists() {
            std::fs::copy(&pregenerated, out_path.join("cronet_bindings.rs"))
                .expect("Failed to copy pre-generated bindings");
            println!("cargo:warning=Using pre-generated Linux bindings");
        } else {
            panic!("Pre-generated Linux bindings not found at {:?}", pregenerated);
        }
    } else if target.contains("darwin") || target.contains("aarch64-apple") {
        let pregenerated = PathBuf::from(&dir).join("src/cronet_bindings_mac.rs");
        if pregenerated.exists() {
            std::fs::copy(&pregenerated, out_path.join("cronet_bindings.rs"))
                .expect("Failed to copy pre-generated bindings");
            println!("cargo:warning=Using pre-generated macOS bindings");
        } else {
            panic!("Pre-generated macOS bindings not found at {:?}", pregenerated);
        }
    } else {
        // For Windows, generate bindings normally
        let bindings = bindgen::Builder::default()
            .header_contents(
                "wrapper.h",
                "#include <stdbool.h>\n#include \"cronet.idl_c.h\"",
            )
            .clang_arg(format!("-I{}", include_dir.display()))
            .parse_callbacks(Box::new(bindgen::CargoCallbacks::new()))
            .generate()
            .expect("Unable to generate bindings");

        bindings
            .write_to_file(out_path.join("cronet_bindings.rs"))
            .expect("Couldn't write bindings!");
    }

    // 2. Compile Protos (Standard Prost)
    let proto_file = "proto/cronet_engine.proto";

    // For Linux and macOS targets, use pre-generated proto files
    if target.contains("linux") {
        let pregenerated_proto = PathBuf::from(&dir).join("src/cronet_proto_linux.rs");
        if pregenerated_proto.exists() {
            std::fs::copy(&pregenerated_proto, out_path.join("cronet.engine.v1.rs"))
                .expect("Failed to copy pre-generated proto");
            println!("cargo:warning=Using pre-generated Linux proto");
        } else {
            panic!("Pre-generated Linux proto not found at {:?}", pregenerated_proto);
        }
    } else if target.contains("darwin") || target.contains("aarch64-apple") {
        let pregenerated_proto = PathBuf::from(&dir).join("src/cronet_proto_mac.rs");
        if pregenerated_proto.exists() {
            std::fs::copy(&pregenerated_proto, out_path.join("cronet.engine.v1.rs"))
                .expect("Failed to copy pre-generated proto");
            println!("cargo:warning=Using pre-generated macOS proto");
        } else {
            panic!("Pre-generated macOS proto not found at {:?}", pregenerated_proto);
        }
    } else if std::path::Path::new(proto_file).exists() {
        // For Windows, compile protos normally
        let mut config = prost_build::Config::new();
        config.type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]");
        config.type_attribute("cronet.engine.v1.ExecuteRequest", "#[serde(default)]");
        config.type_attribute("cronet.engine.v1.TargetRequest", "#[serde(default)]");
        config.type_attribute("cronet.engine.v1.ExecutionConfig", "#[serde(default)]");
        config.type_attribute("cronet.engine.v1.ExecuteResponse", "#[serde(default)]");

        config.field_attribute(
            "cronet.engine.v1.TargetRequest.body",
            "#[serde(with = \"hex::serde\")]",
        );
        config.field_attribute(
            "cronet.engine.v1.TargetResponse.body",
            "#[serde(with = \"hex::serde\")]",
        );
        config
            .compile_protos(&[proto_file], &["proto"])
            .expect("failed to compile protos");
    }

    // 3. Link against the Cronet DLL/SO
    println!("cargo:rustc-link-search=native={}", lib_dir.display());
    println!("cargo:rustc-link-lib=dylib=cronet");

    // Linux: Set rpath to look for .so in the same directory as the extension module
    if target.contains("linux") {
        println!("cargo:rustc-link-arg=-Wl,-rpath,$ORIGIN");
        println!("cargo:rustc-link-arg=-Wl,--enable-new-dtags");
    }

    // macOS: Set rpath to look for dylib in the same directory as the extension module
    if target.contains("darwin") || target.contains("apple") {
        println!("cargo:rustc-link-arg=-Wl,-rpath,@loader_path");
    }

    // 4. Copy library to output directory for packaging
    let out_dir = env::var("OUT_DIR").unwrap();
    let target_dir = PathBuf::from(&out_dir)
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();

    #[cfg(target_os = "windows")]
    {
        // Windows: Copy DLL with version to target directory
        let dll_name = format!("cronet.{}.dll", version);
        let src_dll = lib_dir.join("cronet.dll");
        let dst_dll = target_dir.join(&dll_name);

        if src_dll.exists() {
            let should_copy = if dst_dll.exists() {
                let src_meta = std::fs::metadata(&src_dll).ok();
                let dst_meta = std::fs::metadata(&dst_dll).ok();
                match (src_meta, dst_meta) {
                    (Some(s), Some(d)) => s.modified().ok() > d.modified().ok(),
                    _ => true,
                }
            } else {
                true
            };

            if should_copy {
                std::fs::copy(&src_dll, &dst_dll).expect("Failed to copy DLL to target dir");
                println!(
                    "cargo:warning=Copied {} to {}",
                    src_dll.display(),
                    dst_dll.display()
                );
            }
        }

        // Also copy to python package directory for maturin to include
        let python_dir = PathBuf::from(&dir).join("python").join("cycronet");
        if python_dir.exists() {
            let python_dll = python_dir.join(&dll_name);
            if src_dll.exists() {
                std::fs::copy(&src_dll, &python_dll).ok();
                println!("cargo:warning=Copied {} to python package directory", dll_name);
            }
        }

        println!("cargo:rerun-if-changed={}", src_dll.display());
    }

    #[cfg(target_os = "linux")]
    {
        // Linux: Copy SO with version to target directory
        let so_name = format!("libcronet.{}.so", version);
        let src_so = lib_dir.join("libcronet.so");
        let dst_so = target_dir.join(&so_name);

        if src_so.exists() {
            let should_copy = if dst_so.exists() {
                let src_meta = std::fs::metadata(&src_so).ok();
                let dst_meta = std::fs::metadata(&dst_so).ok();
                match (src_meta, dst_meta) {
                    (Some(s), Some(d)) => s.modified().ok() > d.modified().ok(),
                    _ => true,
                }
            } else {
                true
            };

            if should_copy {
                std::fs::copy(&src_so, &dst_so).expect("Failed to copy SO to target dir");
                println!(
                    "cargo:warning=Copied {} to {}",
                    src_so.display(),
                    dst_so.display()
                );
            }
        }

        // Also copy to python package directory for maturin to include
        let python_dir = PathBuf::from(&dir).join("python").join("cycronet");
        if python_dir.exists() {
            let python_so = python_dir.join(&so_name);
            if src_so.exists() {
                std::fs::copy(&src_so, &python_so).ok();
                println!("cargo:warning=Copied SO to python package directory");
            }
        }

        println!("cargo:rerun-if-changed={}", src_so.display());
    }

    #[cfg(target_os = "macos")]
    {
        // macOS: Copy dylib with version to target directory
        let dylib_name = format!("libcronet.{}.dylib", version);
        let src_dylib = lib_dir.join("libcronet.dylib");
        let dst_dylib = target_dir.join(&dylib_name);

        if src_dylib.exists() {
            let should_copy = if dst_dylib.exists() {
                let src_meta = std::fs::metadata(&src_dylib).ok();
                let dst_meta = std::fs::metadata(&dst_dylib).ok();
                match (src_meta, dst_meta) {
                    (Some(s), Some(d)) => s.modified().ok() > d.modified().ok(),
                    _ => true,
                }
            } else {
                true
            };

            if should_copy {
                std::fs::copy(&src_dylib, &dst_dylib).expect("Failed to copy dylib to target dir");
                println!(
                    "cargo:warning=Copied {} to {}",
                    src_dylib.display(),
                    dst_dylib.display()
                );
            }
        }

        // Also copy to python package directory for maturin to include
        let python_dir = PathBuf::from(&dir).join("python").join("cycronet");
        if python_dir.exists() {
            let python_dylib = python_dir.join(&dylib_name);
            if src_dylib.exists() {
                std::fs::copy(&src_dylib, &python_dylib).ok();
                println!("cargo:warning=Copied dylib to python package directory");
            }
        }

        println!("cargo:rerun-if-changed={}", src_dylib.display());
    }

    println!("cargo:rerun-if-changed=build.rs");
}
