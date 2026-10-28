pub(crate) const BINARIES: &[(&str, &[u8])] = &[
    ("linuxdeploy", include_bytes!("../binaries/linuxdeploy")),
    ("patchelf", include_bytes!("../binaries/patchelf")),
    ("strip", include_bytes!("../binaries/strip")),
];

pub(crate) const IMAGES: &[(&str, &str)] = &[("arch", include_str!("../images/arch/Dockerfile"))];

pub(crate) const HELPER_INCLUDES: &[(&str, &str)] =
    &[("common", include_str!("../helpers/_common.sh"))];

pub(crate) const HELPERS: &[(&str, &str)] = &[
    ("gamescope", include_str!("../helpers/gamescope.sh")),
    ("java", include_str!("../helpers/java.sh")),
    ("javafx", include_str!("../helpers/javafx.sh")),
    ("uv", include_str!("../helpers/uv.sh")),
    ("wine-init", include_str!("../helpers/wine-init.sh")),
    ("wine-mono", include_str!("../helpers/wine-mono.sh")),
    ("wine", include_str!("../helpers/wine.sh")),
];
