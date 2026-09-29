# Monochrome on macOS

These scripts build and install a separate Apple Silicon application. They do not modify an existing browser or its profile. Keep this monochrome directory together when moving it into a source fork.

From a complete Chromium `src` checkout, with `depot_tools` on `PATH`, copy `args.gn` into `out/Monochrome/args.gn`, then run:

```sh
gn gen out/Monochrome
caffeinate autoninja -C out/Monochrome chrome
```

This uses a release build with symbols disabled and Apple's linker. A noncomponent build is required so the `.app` can be copied outside the output directory. The executable name follows `PRODUCT_FULLNAME` in `chrome/app/theme/chromium/BRANDING`. Use a distinct bundle ID and set `CrProductDirName` to `Monochrome` in the app's source Info.plist so it has a separate browser profile.

Validate the resulting app before installation:

```sh
python3 monochrome/install_macos.py out/Monochrome/Monochrome.app --check-only
```

Once grayscale behavior has separately passed its visual checks, install and request the default-browser change:

```sh
python3 monochrome/install_macos.py out/Monochrome/Monochrome.app --set-default
open "$HOME/Applications/Monochrome.app"
```

The installer validates bundle metadata and architecture, rejects external symlinks, and smoke-tests browser startup and HTML rendering with temporary profiles. It repeats the check on a staged copy, installs to `~/Applications/Monochrome.app`, and registers the application with LaunchServices. Any previous installation is preserved beside it as `Monochrome.previous-<timestamp>.app`. The startup smoke check does not verify grayscale; use the rendering checks for that.

Omit `--set-default` to install without changing defaults. A locally produced noncomponent Chromium app runs without a Developer ID certificate or notarization. Do not disable Gatekeeper, SIP, or the browser sandbox. These scripts do not remove quarantine attributes or re-sign binaries.

The default helper calls Apple's `NSWorkspace` API for HTTP, waits for the result, then sets HTTPS. macOS may display a consent dialog that must be accepted. An error or refusal stops the sequence. Afterward the helper verifies that both schemes resolve to the installed app's path and bundle ID. HTML file associations are left alone because macOS 26.4+ presents a separate confirmation for them.

The helper also supports read-only status and verification:

```sh
xcrun swiftc -parse-as-library monochrome/default_browser.swift -o /tmp/monochrome-default-browser
/tmp/monochrome-default-browser --status
/tmp/monochrome-default-browser --verify "$HOME/Applications/Monochrome.app"
```

To return to another default browser, use System Settings > Desktop & Dock > Default web browser.

References: [Chromium macOS build instructions](https://github.com/chromium/chromium/blob/main/docs/mac_build_instructions.md), [Chromium arm64 portability notes](https://github.com/chromium/chromium/blob/main/docs/mac_arm64.md), [Apple default application API](https://developer.apple.com/documentation/appkit/nsworkspace/setdefaultapplication(at:toopenurlswithscheme:completion:)), and [Chromium's macOS default-browser implementation](https://github.com/chromium/chromium/blob/main/chrome/browser/shell_integration_mac.mm).
