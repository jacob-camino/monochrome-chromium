#!/usr/bin/env python3
"""Verify a browser's headless rendering without touching its existing profile.

Examples:
  python3 grayscale_smoke.py /path/to/Chromium.app/Contents/MacOS/Chromium
  python3 grayscale_smoke.py --expect-color "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

Requires Pillow. By default tests normal GPU selection and --disable-gpu.
This tests rendered web content, not native macOS/browser toolbar controls.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from PIL import Image


WIDTH, HEIGHT = 800, 640
ROWS = {"css": 80, "inline_svg": 200, "svg_image": 320, "canvas": 440, "iframe": 560}
COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "gray": (128, 128, 128),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
}


class SmokeFailure(RuntimeError):
    pass


def stop_process_group(process: subprocess.Popen[str]) -> None:
    """Stop this isolated browser and any child processes before profile removal."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The main process can exit before helpers; kill only its isolated group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def verify_screenshot(path: Path, expect_color: bool) -> dict:
    if not path.is_file():
        raise SmokeFailure("Browser did not produce a screenshot")
    with Image.open(path) as source:
        image = source.convert("RGB")
    if image.size != (WIDTH, HEIGHT):
        raise SmokeFailure(f"Wrong screenshot size: {image.size}, expected {(WIDTH, HEIGHT)}")

    pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
    colorful_pixels = sum(max(pixel) - min(pixel) > 2 for pixel in pixels)
    maximum_channel_spread = max(max(pixel) - min(pixel) for pixel in pixels)
    if not expect_color and colorful_pixels:
        raise SmokeFailure(
            f"Screenshot contains {colorful_pixels} non-neutral pixels; "
            f"maximum RGB channel spread is {maximum_channel_spread} (allowed: 2)"
        )
    if expect_color and colorful_pixels < 100_000:
        raise SmokeFailure(f"Color control has only {colorful_pixels} colorful pixels")

    samples = {}
    for row_name, y in ROWS.items():
        row_samples = {}
        for index, (name, original) in enumerate(COLORS.items()):
            x = 70 + index * 120
            # A 9x9 center patch rejects isolated correct pixels and edge effects.
            patch = [image.getpixel((xx, yy)) for yy in range(y - 4, y + 5)
                     for xx in range(x - 4, x + 5)]
            sample = image.getpixel((x, y))
            row_samples[name] = sample
            if any(max(abs(a - b) for a, b in zip(pixel, sample)) > 2 for pixel in patch):
                raise SmokeFailure(f"{row_name}/{name} does not have a solid center patch")
            if expect_color or name in {"gray", "white", "black"}:
                if max(abs(a - b) for a, b in zip(sample, original)) > 8:
                    raise SmokeFailure(f"{row_name}/{name}: got {sample}, expected approximately {original}")
            else:
                # Cover matrices applied in encoded sRGB or linear-light space.
                # Neutral controls above independently reject blank screenshots.
                bounds = {"red": (35, 170), "green": (115, 245), "blue": (5, 135)}
                lower, upper = bounds[name]
                if not lower <= sample[0] <= upper:
                    raise SmokeFailure(
                        f"{row_name}/{name}: brightness {sample[0]} outside [{lower}, {upper}]"
                    )
        if not expect_color:
            red, green, blue = (row_samples[name][0] for name in ("red", "green", "blue"))
            if not green > red > blue:
                raise SmokeFailure(f"{row_name}: grayscale primary brightness ordering is incorrect")
        samples[row_name] = row_samples

    # Every rendering path should produce matching swatches with the same matrix.
    baseline = samples["css"]
    for row_name, row_samples in samples.items():
        for name, sample in row_samples.items():
            if max(abs(a - b) for a, b in zip(sample, baseline[name])) > 3:
                raise SmokeFailure(f"{row_name}/{name} differs from the CSS rendering path")
    return {"size": list(image.size), "colorful_pixels": colorful_pixels,
            "maximum_channel_spread": maximum_channel_spread, "samples": samples}


def run_mode(executable: Path, mode: str, args: argparse.Namespace) -> dict:
    fixture = Path(__file__).with_name("grayscale_fixture.html")
    if not fixture.is_file():
        raise SmokeFailure(f"Missing fixture: {fixture}")
    with tempfile.TemporaryDirectory(prefix=f"monochrome-smoke-{mode}-") as temporary:
        temporary_path = Path(temporary)
        screenshot = temporary_path / "screenshot.png"
        command = [
            str(executable), "--headless=new", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--disable-component-update", "--disable-sync",
            "--disable-background-mode", "--use-mock-keychain",
            "--metrics-recording-only", "--force-device-scale-factor=1", "--hide-scrollbars",
            f"--window-size={WIDTH},{HEIGHT}", "--virtual-time-budget=1500",
            "--run-all-compositor-stages-before-draw", f"--user-data-dir={temporary_path / 'profile'}",
            f"--screenshot={screenshot}",
        ]
        if mode == "disabled":
            command.append("--disable-gpu")
        command.append(fixture.resolve().as_uri())
        log_path = temporary_path / "browser.log"
        with log_path.open("w+b") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                deadline = time.monotonic() + args.timeout
                while True:
                    if process.poll() is not None:
                        if process.returncode:
                            raise SmokeFailure(f"Browser exited {process.returncode}")
                        break
                    if screenshot.is_file():
                        try:
                            # PNG verification rejects a partially written screenshot.
                            with Image.open(screenshot) as candidate:
                                candidate.verify()
                            break
                        except (OSError, SyntaxError):
                            pass
                    if time.monotonic() >= deadline:
                        raise SmokeFailure(f"Browser exceeded {args.timeout}s timeout without a complete PNG")
                    time.sleep(0.1)
                try:
                    process.wait(timeout=2)
                    exited_on_own = True
                    if process.returncode:
                        raise SmokeFailure(f"Browser exited {process.returncode} after rendering")
                except subprocess.TimeoutExpired:
                    # macOS Chrome can retain background services after --screenshot.
                    exited_on_own = False
                result = verify_screenshot(screenshot, args.expect_color)
                result["mode"] = mode
                result["expect_color"] = args.expect_color
                result["browser_exited_on_own"] = exited_on_own
                if args.output_dir:
                    args.output_dir.mkdir(parents=True, exist_ok=True)
                    destination = args.output_dir / f"{mode}-{'color' if args.expect_color else 'grayscale'}.png"
                    shutil.copy2(screenshot, destination)
                    result["screenshot"] = str(destination.resolve())
                return result
            except SmokeFailure as error:
                log.flush()
                browser_log = log_path.read_text(encoding="utf-8", errors="replace")
                raise SmokeFailure(f"{mode}: {error}\nBrowser log:\n{browser_log[-6000:]}") from error
            finally:
                stop_process_group(process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("executable", type=Path, help="Path to the browser's Mach-O executable")
    parser.add_argument("--expect-color", action="store_true", help="Validate an unmodified browser as a color control")
    parser.add_argument("--gpu-mode", choices=("both", "normal", "disabled"), default="both")
    parser.add_argument("--timeout", type=float, default=60, help="Browser timeout per mode in seconds (default: 60)")
    parser.add_argument("--output-dir", type=Path, help="Optionally retain screenshots and a JSON report")
    args = parser.parse_args()
    executable = args.executable.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        parser.error(f"Not an executable file: {executable}")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    modes = ("normal", "disabled") if args.gpu_mode == "both" else (args.gpu_mode,)
    results = []
    try:
        for mode in modes:
            result = run_mode(executable, mode, args)
            results.append(result)
            print(f"PASS {mode}: {result['colorful_pixels']} colorful pixels; "
                  f"CSS samples {result['samples']['css']}", flush=True)
    except (SmokeFailure, OSError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if args.output_dir:
        report = {"executable": str(executable), "results": results}
        report_path = args.output_dir / f"{'color' if args.expect_color else 'grayscale'}-report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
