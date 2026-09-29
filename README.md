# Monochrome

Monochrome is a Chromium fork for browsing in grayscale. It is based on Chromium
154.0.8037.58 (upstream commit `a654841425914cbb703a2931e07b70a83aedbafd`) and targets
Apple Silicon Macs.

The browser desaturates the completed root render pass, after page content has
been composited. This covers Chromium-rendered browser controls and content such
as images, CSS, SVG, canvas, and embedded frames. The GPU and software rendering
paths both apply the conversion. macOS overlay promotion is disabled so video
cannot bypass the conversion through a separate Core Animation layer.

The grayscale behavior is always on. There is no website permission, extension,
or page-injected stylesheet to maintain. Underlying documents and downloaded
files retain their original colors. Native macOS interfaces, including system
dialogs and window controls, are outside Chromium's renderer and can retain
system colors. Forcing video through the compositor may increase power use;
content requiring a protected overlay may not display.

The application is named **Monochrome**, uses bundle identifier
`io.github.jacobcamino.Monochrome`, and stores its profile in
`~/Library/Application Support/Monochrome`.

## Build on macOS

Install Xcode and Chromium's [depot_tools](https://chromium.googlesource.com/chromium/tools/depot_tools.git).
Create a workspace with this repository checked out as its `src` subdirectory.
In the workspace (beside `src`), create `.gclient`:

```python
solutions = [{
    "name": "src",
    "url": "https://github.com/jacob-camino/monochrome-chromium.git",
    "managed": False,
    "custom_deps": {},
    "custom_vars": {"checkout_pgo_profiles": False},
}]
target_os = []
```

From `src`, run:

```sh
python3 monochrome/build_mac.py --depot-tools /absolute/path/to/depot_tools --sync
```

The script syncs dependencies at their pinned revisions, runs Chromium's hooks,
generates a native arm64 release configuration, builds `chrome` and
`viz_unittests`, and runs the grayscale and related rendering regressions.
It uses six build jobs by default; adjust with `--jobs`. It stops if free disk
space drops below 15 GiB and can be rerun to resume. Build logs and status are
in `out/Monochrome/build-logs/`. A full checkout and build can take hours and
requires substantial free disk space.

## Verify and install

The screenshot verifier requires Pillow. It checks colored fixtures rendered
through CSS, SVG, images, canvas, and an iframe in normal and GPU-disabled modes.
It verifies neutral pixels and known swatches so a blank page cannot pass:

```sh
python3 monochrome/grayscale_smoke.py out/Monochrome/Monochrome.app/Contents/MacOS/Monochrome --output-dir out/Monochrome/grayscale-checks
python3 monochrome/install_macos.py out/Monochrome/Monochrome.app --set-default
```

The installer validates and smoke-tests a staged copy, installs to
`~/Applications/Monochrome.app`, and requests the HTTP/HTTPS default through
macOS. Complete any system confirmation dialog. It verifies the result and
reports an error if the change did not succeed. Omit `--set-default` to install
without changing the default browser.

This locally built fork does not include Chrome's automatic update service.
Keep it current with upstream Chromium security releases and rebuild it before
relying on it for everyday browsing. See [Chromium's Mac build instructions](https://github.com/chromium/chromium/blob/main/docs/mac_build_instructions.md)
for upstream prerequisites and troubleshooting.
