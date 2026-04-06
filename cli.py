import json
import os
import shutil
import socket
import sys
from pathlib import Path

from config import print_sample_config
from hooks import SOCKET_PATH, install_hooks, uninstall_hooks

APP_DIR = Path.home() / "Applications" / "SpookyCat.app"
CLI_PATH = Path.home() / ".local" / "bin" / "spookycat"


def send_command(msg):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(SOCKET_PATH)
        s.sendall(json.dumps(msg).encode() + b"\n")
        s.close()
    except OSError:
        print("SpookyCat is not running.")
        sys.exit(1)


def install_app():
    project_dir = Path(__file__).parent.resolve()
    uv_path = shutil.which("uv")
    if not uv_path:
        print("Error: uv not found in PATH")
        sys.exit(1)

    contents = APP_DIR / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    exe = macos / "SpookyCat"
    exe.write_text(f'#!/bin/bash\ncd "{project_dir}"\nexec "{uv_path}" run python main.py\n')
    exe.chmod(0o755)

    plist = contents / "Info.plist"
    plist.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>SpookyCat</string>
    <key>CFBundleIdentifier</key>
    <string>lol.pjw.spookycat</string>
    <key>CFBundleName</key>
    <string>SpookyCat</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
""")

    print(f"Installed to {APP_DIR}")
    print("Launch from Raycast/Spotlight — look for 'SpookyCat'.")


def uninstall_app():
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
        print(f"Removed {APP_DIR}")
    else:
        print("SpookyCat.app not found in ~/Applications.")


def install_cli():
    project_dir = Path(__file__).parent.resolve()
    uv_path = shutil.which("uv")
    if not uv_path:
        print("Error: uv not found in PATH")
        sys.exit(1)

    CLI_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLI_PATH.write_text(
        f'#!/bin/bash\ncd "{project_dir}"\nexec "{uv_path}" run python main.py "$@"\n'
    )
    CLI_PATH.chmod(0o755)
    print(f"Installed CLI to {CLI_PATH}")
    if str(CLI_PATH.parent) not in os.environ.get("PATH", ""):
        print(f"  Note: add {CLI_PATH.parent} to your PATH if not already there")


def uninstall_cli():
    if CLI_PATH.exists():
        CLI_PATH.unlink()
        print(f"Removed {CLI_PATH}")
    else:
        print(f"CLI not found at {CLI_PATH}")


def cmd_set_workspace(args):
    if len(args) < 3:
        print("Usage: spookycat set-workspace KEY ICON WORKSPACE_DIR")
        sys.exit(1)
    try:
        key = int(args[0])
    except ValueError:
        print(f"Error: KEY must be integer 0-5, got '{args[0]}'")
        sys.exit(1)
    if not 0 <= key <= 5:
        print(f"Error: KEY must be 0-5, got {key}")
        sys.exit(1)
    send_command(
        {
            "command": "set-workspace",
            "key": key,
            "icon": args[1],
            "workspace": args[2],
        }
    )
    print(f"Key {key}: icon={args[1]} workspace={args[2]}")


def main():
    from main import run

    log_level = "info"
    args = sys.argv[1:]

    filtered = []
    for arg in args:
        if arg.startswith("--log-level="):
            log_level = arg.split("=", 1)[1]
        else:
            filtered.append(arg)

    if filtered:
        cmd = filtered[0]
        simple_commands = {
            "install-hooks": install_hooks,
            "uninstall-hooks": uninstall_hooks,
            "install-app": install_app,
            "uninstall-app": uninstall_app,
            "install-cli": install_cli,
            "uninstall-cli": uninstall_cli,
            "print-sample-config": print_sample_config,
        }
        if cmd in simple_commands:
            simple_commands[cmd]()
        elif cmd == "set-workspace":
            cmd_set_workspace(filtered[1:])
        else:
            print(f"Unknown command: {cmd}")
            print("Commands: install-hooks, uninstall-hooks, install-app,")
            print("  uninstall-app, install-cli, uninstall-cli,")
            print("  print-sample-config, set-workspace KEY ICON DIR")
            sys.exit(1)
        return

    run(log_level)


if __name__ == "__main__":
    main()
