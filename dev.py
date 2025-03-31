import os
import subprocess
import sys


def main():
    os.environ["NASTOOL_CONFIG"] = os.path.join("src", "config", "config.yaml")

    cmd = [sys.executable, os.path.join("src", "run.py")]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
