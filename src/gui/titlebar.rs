//! Ask Windows to draw the window frame dark.
//!
//! Without this the OS paints a light title bar above a fully dark application,
//! which reads as a black-and-white clash rather than one coherent surface.
//! Every failure path here is silent on purpose: a light frame is cosmetic, so
//! it must never take the viewer down.

/// Switch the native window frame to dark. No-op outside Windows.
#[cfg(target_os = "windows")]
pub fn make_dark(title: &str) {
    // DWMWA_USE_IMMERSIVE_DARK_MODE moved between Windows 10 builds.
    const ATTR_CURRENT: u32 = 20;
    const ATTR_PRE_20H1: u32 = 19;

    #[link(name = "user32")]
    unsafe extern "system" {
        fn FindWindowW(class: *const u16, window: *const u16) -> isize;
    }
    #[link(name = "dwmapi")]
    unsafe extern "system" {
        fn DwmSetWindowAttribute(
            hwnd: isize,
            attribute: u32,
            value: *const i32,
            size: u32,
        ) -> i32;
    }

    let wide: Vec<u16> = title.encode_utf16().chain(std::iter::once(0)).collect();
    // SAFETY: `wide` is a NUL-terminated UTF-16 buffer that outlives the call,
    // and a null class name is the documented "any class" wildcard.
    let hwnd = unsafe { FindWindowW(std::ptr::null(), wide.as_ptr()) };
    if hwnd == 0 {
        return;
    }

    let enabled: i32 = 1;
    for attribute in [ATTR_CURRENT, ATTR_PRE_20H1] {
        // SAFETY: `hwnd` came from FindWindowW, and `enabled` is a live BOOL
        // whose size we pass explicitly, as the API requires.
        let status = unsafe {
            DwmSetWindowAttribute(
                hwnd,
                attribute,
                &enabled,
                std::mem::size_of::<i32>() as u32,
            )
        };
        if status == 0 {
            return;
        }
    }
}

#[cfg(not(target_os = "windows"))]
pub fn make_dark(_title: &str) {}
