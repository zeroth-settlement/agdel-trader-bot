#!/usr/bin/env python3
"""
Quick start script for the Pyrana Bridge Server.
Kills any existing process on port 9002, then starts the bridge server.
"""

import subprocess
import sys
import os
import signal
import time

BRIDGE_PORT = 9002
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))


def find_process_on_port(port):
    """Find PID of process using the specified port."""
    try:
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return [int(pid) for pid in pids if pid]
    except Exception as e:
        print(f"Error finding process: {e}")
    return []


def kill_process(pid):
    """Kill a process by PID."""
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"  Sent SIGTERM to PID {pid}")
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            print(f"  Sent SIGKILL to PID {pid}")
        except OSError:
            pass
        return True
    except OSError as e:
        print(f"  Error killing PID {pid}: {e}")
        return False


def kill_port(port):
    """Kill all processes on a given port."""
    pids = find_process_on_port(port)
    if pids:
        print(f"Found existing process(es) on port {port}: {pids}")
        for pid in pids:
            kill_process(pid)
        return True
    else:
        print(f"No existing process found on port {port}")
        return False


def main():
    print("=" * 50)
    print("  Pyrana Bridge Server")
    print("=" * 50)
    print()

    # Kill existing process on bridge port
    killed = kill_port(BRIDGE_PORT)
    if killed:
        time.sleep(1)

    # Start bridge server
    os.chdir(SERVER_DIR)
    bridge_path = os.path.join(SERVER_DIR, 'bridge_server.py')

    print(f"\nStarting bridge server...")
    print(f"Serving from: {SERVER_DIR}")
    print(f"\nDashboard:  http://localhost:{BRIDGE_PORT}/")
    print(f"Health:     http://localhost:{BRIDGE_PORT}/health")
    print(f"\nPress Ctrl+C to stop.\n")
    print("-" * 50)

    bridge = subprocess.Popen(
        [sys.executable, bridge_path],
        stderr=subprocess.PIPE
    )

    try:
        while True:
            if bridge.poll() is not None:
                print(f"\nBridge server stopped unexpectedly!")
                if bridge.stderr:
                    stderr_output = bridge.stderr.read()
                    if isinstance(stderr_output, bytes):
                        stderr_output = stderr_output.decode()
                    if stderr_output.strip():
                        for line in stderr_output.strip().splitlines():
                            print(f"  {line}")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        if bridge:
            bridge.terminate()
            print(f"Stopped bridge server (port {BRIDGE_PORT})")
        print("Done.")
        sys.exit(0)


if __name__ == '__main__':
    main()
