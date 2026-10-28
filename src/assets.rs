use anyhow::{Context, Result};

const BINARIES: &[(&str, &[u8])] = &[
    ("linuxdeploy", include_bytes!("../binaries/linuxdeploy")),
    ("patchelf", include_bytes!("../binaries/patchelf")),
];

const IMAGES: &[(&str, &str)] = &[("arch", include_str!("../images/arch/Dockerfile"))];

const HELPER_INCLUDES: &[(&str, &str)] = &[("common", include_str!("../helpers/_common.sh"))];

const HELPERS: &[(&str, &str)] = &[
    ("gamescope", include_str!("../helpers/gamescope.sh")),
    ("java", include_str!("../helpers/java.sh")),
    ("javafx", include_str!("../helpers/javafx.sh")),
    ("linuxdeploy", include_str!("../helpers/linuxdeploy.sh")),
    ("uv", include_str!("../helpers/uv.sh")),
    ("wine-init", include_str!("../helpers/wine-init.sh")),
    ("wine-mono", include_str!("../helpers/wine-mono.sh")),
    ("wine", include_str!("../helpers/wine.sh")),
];

pub(crate) fn binary(name: &str) -> Result<&'static [u8]> {
    BINARIES
        .iter()
        .find(|(key, _)| *key == name)
        .map(|(_, bytes)| *bytes)
        .with_context(|| format!("missing embedded binary: {name}"))
}

pub(crate) fn image(name: &str) -> Result<&'static str> {
    IMAGES
        .iter()
        .find(|(key, _)| *key == name)
        .map(|(_, source)| *source)
        .with_context(|| format!("missing embedded image: {name}"))
}

pub(crate) fn image_names() -> impl Iterator<Item = &'static str> {
    IMAGES.iter().map(|(name, _)| *name)
}

pub(crate) fn helper(name: &str) -> Result<&'static str> {
    HELPERS
        .iter()
        .find(|(key, _)| *key == name)
        .map(|(_, source)| *source)
        .with_context(|| format!("missing embedded helper: {name}"))
}

pub(crate) fn helper_names() -> impl Iterator<Item = &'static str> {
    HELPERS.iter().map(|(name, _)| *name)
}

pub(crate) fn helper_include(name: &str) -> Result<&'static str> {
    HELPER_INCLUDES
        .iter()
        .find(|(key, _)| *key == name)
        .map(|(_, source)| *source)
        .with_context(|| format!("unknown helper include: {name}"))
}
