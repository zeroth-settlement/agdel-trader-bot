#!/usr/bin/env python3
"""Launch the AgDel Trading Server on port 9004."""

import os
import signal
import subprocess
import sys


def kill_port(port: int):
    """Kill any process on the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True,
        )
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            if pid:
                os.kill(int(pid), signal.SIGTERM)
                print(f"  Killed PID {pid} on port {port}")
    except Exception:
        pass


if __name__ == "__main__":
    print("=" * 50)
    print("  AgDel Trader Bot — Starting Trading Server")
    print("=" * 50)
    print()

    # Kill existing process on port 9004
    kill_port(9004)

    # Launch trading server
    import uvicorn
    from trading_server import app

    uvicorn.run(app, host="0.0.0.0", port=9004)
