
#![allow(non_upper_case_globals)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

pub mod cronet;

#[cfg(feature = "server")]
pub mod service;

#[cfg(feature = "python")]
pub mod python;

// Include generated bindings
pub mod cronet_c {
    include!(concat!(env!("OUT_DIR"), "/cronet_bindings.rs"));
}

// Include generated proto code
pub mod cronet_pb {
    include!(concat!(env!("OUT_DIR"), "/cronet.engine.v1.rs"));
}

use std::sync::atomic::AtomicBool;

/// Global debug mode flag - when enabled, requests are logged to req.txt
pub static DEBUG_MODE: AtomicBool = AtomicBool::new(false);

/// Global verbose mode flag - when enabled, shows detailed debug information
pub static VERBOSE_MODE: AtomicBool = AtomicBool::new(false);
