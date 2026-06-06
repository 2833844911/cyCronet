/**
 * seh_guard.c - Windows SEH wrappers for Cronet FFI calls.
 *
 * Wraps dangerous Cronet_*_Destroy calls in __try/__except so that
 * access violations (0xc0000005) inside cronet.dll are caught and
 * returned as error codes instead of crashing the process.
 */

#ifdef _WIN32

#include <windows.h>
#include <stdio.h>

typedef void* Cronet_Ptr;
typedef void (*Cronet_DestroyFn)(Cronet_Ptr);
typedef int  (*Cronet_ShutdownFn)(Cronet_Ptr);

/* Generic safe destroy: calls destroy_fn(ptr) inside SEH.
 * Returns 0 on success, or the Windows exception code on failure. */
unsigned long seh_safe_destroy(Cronet_Ptr ptr, Cronet_DestroyFn destroy_fn) {
    if (!ptr || !destroy_fn) return 0;
    __try {
        destroy_fn(ptr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        unsigned long code = GetExceptionCode();
        fprintf(stderr, "[cycronet/SEH] Caught exception 0x%08lx during Destroy(%p), skipped.\n", code, ptr);
        return code;
    }
    return 0;
}

/* Safe engine shutdown: calls shutdown_fn(ptr) inside SEH.
 * Returns the original return value, or -1 on exception. */
int seh_safe_shutdown(Cronet_Ptr ptr, Cronet_ShutdownFn shutdown_fn) {
    if (!ptr || !shutdown_fn) return 0;
    __try {
        return shutdown_fn(ptr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        unsigned long code = GetExceptionCode();
        fprintf(stderr, "[cycronet/SEH] Caught exception 0x%08lx during Shutdown(%p), skipped.\n", code, ptr);
        return -1;
    }
}

/* Generic safe one-pointer call: calls call_fn(ptr) inside SEH.
 * This is intentionally separate from seh_safe_destroy so Rust call sites
 * do not label non-destroy operations (Cancel, Runnable_Run) as Destroy. */
unsigned long seh_safe_call1(Cronet_Ptr ptr, Cronet_DestroyFn call_fn) {
    if (!ptr || !call_fn) return 0;
    __try {
        call_fn(ptr);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        unsigned long code = GetExceptionCode();
        fprintf(stderr, "[cycronet/SEH] Caught exception 0x%08lx during call(%p), skipped.\n", code, ptr);
        return code;
    }
    return 0;
}

/* Safe generic call with no return value */
unsigned long seh_safe_call(void (*fn)(void)) {
    if (!fn) return 0;
    __try {
        fn();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        unsigned long code = GetExceptionCode();
        fprintf(stderr, "[cycronet/SEH] Caught exception 0x%08lx during call(%p), skipped.\n", code, (void*)fn);
        return code;
    }
    return 0;
}

#endif /* _WIN32 */
