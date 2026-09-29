#!/usr/bin/env python3
"""Build the native Mac app while preserving a reserve of free disk space."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--depot-tools', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--sync', action='store_true', help='Sync pinned dependencies and run hooks first')
    parser.add_argument('--reserve-gib', type=float, default=15)
    args = parser.parse_args()
    if args.jobs < 1 or args.reserve_gib < 1:
        parser.error('jobs and reserve-gib must be positive')
    source = Path(__file__).resolve().parents[1]
    if not (source / 'DEPS').is_file() or not (source / 'chrome').is_dir():
        parser.error('Place this script in the Chromium checkout under monochrome/')
    depot = args.depot_tools.expanduser().resolve()
    if not (depot / 'gclient').is_file():
        parser.error('depot-tools does not contain gclient')
    env = dict(os.environ)
    env['PATH'] = f'{depot}:{env["PATH"]}'
    env['DEPOT_TOOLS_UPDATE'] = '0'
    env['PYTHONUNBUFFERED'] = '1'
    output = source / 'out/Monochrome'
    output.mkdir(parents=True, exist_ok=True)
    logs = output / 'build-logs'
    logs.mkdir(exist_ok=True)
    state = logs / 'status.json'

    def status(stage, result, **extra):
        payload = dict(stage=stage, status=result, updated=time.strftime('%Y-%m-%dT%H:%M:%S%z'), **extra)
        state.write_text(json.dumps(payload, indent=2) + '\n')
        print(json.dumps(payload), flush=True)

    def run(stage, command, cwd):
        free = shutil.disk_usage(source).free
        if free < args.reserve_gib * 1024**3:
            status(stage, 'disk-space-required', free_gib=round(free / 1024**3, 1))
            raise SystemExit('Free more disk space before resuming the build.')
        logfile = logs / f'{stage}.log'
        status(stage, 'running', command=command, log=str(logfile))
        with logfile.open('a') as log:
            log.write('\nStarting: ' + repr(command) + '\n')
            log.flush()
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while child.poll() is None:
                    if shutil.disk_usage(source).free < args.reserve_gib * 1024**3:
                        status(stage, 'disk-space-required')
                        raise SystemExit('Build stopped to preserve free disk space. It can be resumed.')
                    time.sleep(5)
                if child.returncode:
                    status(stage, 'failed', exit_code=child.returncode, log=str(logfile))
                    raise SystemExit(f'{stage} failed; see {logfile}')
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
        status(stage, 'passed', log=str(logfile))

    if args.sync:
        run('sync', [str(depot / 'gclient'), 'sync', '--no-history', '--nohooks', '-j', str(args.jobs)], source.parent)
        run('hooks', [str(depot / 'gclient'), 'runhooks', '-j', str(args.jobs)], source.parent)
    config = Path(__file__).with_name('args.gn').read_text()
    (output / 'args.gn').write_text(config)
    run('generate', [str(depot / 'gn'), 'gen', 'out/Monochrome'], source)
    run('compile', [str(depot / 'autoninja'), '-C', 'out/Monochrome', '-j', str(args.jobs), 'chrome', 'viz_unittests'], source)
    filters = '*Grayscale*:*RendererPixelTest.SimpleDamageRect*:*SoftwareRendererTestPartialSwap*:*SoftwareRendererTestShouldClearRootRenderPass*:CALayerOverlayTest.*:CALayerOverlayRPDQTest.*'
    run('rendering-tests', [str(output / 'viz_unittests'), f'--gtest_filter={filters}', '--test-launcher-jobs=2', '--test-launcher-retry-limit=0'], source)
    app = output / 'Monochrome.app'
    if not app.is_dir():
        status('build', 'failed', reason='Expected Monochrome.app is missing')
        raise SystemExit('Build finished but expected application bundle is missing.')
    status('build', 'built-awaiting-validation', application=str(app))


if __name__ == '__main__':
    main()
