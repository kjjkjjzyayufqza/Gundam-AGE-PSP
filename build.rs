fn main() {
    // Embed the egui default app icon into the Windows PE so Explorer shows it
    // on age_viewer.exe. Runtime window/taskbar icon is also set from the PNG
    // in src/gui.rs via ViewportBuilder::with_icon.
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let mut res = winresource::WindowsResource::new();
        res.set_icon("assets/icon.ico");
        res.set("ProductName", "age_viewer");
        res.set("FileDescription", "Gundam AGE PSP model/texture viewer");
        res.set("LegalCopyright", "Research tools — no game data included");
        if let Err(err) = res.compile() {
            // Soft-fail when a Windows RC toolchain is missing (e.g. odd CI images).
            println!("cargo:warning=failed to embed Windows icon/resources: {err}");
        }
    }

    println!("cargo:rerun-if-changed=assets/icon.ico");
    println!("cargo:rerun-if-changed=assets/icon.png");
    println!("cargo:rerun-if-changed=build.rs");
}
