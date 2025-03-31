import os
import shutil
import subprocess
import sys
import tempfile


if __name__ == "__main__":
    with open("src/config/config.yaml", "r", encoding="utf-8") as f:
        config = f.read()
    dir = tempfile.mkdtemp()
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".yaml", mode="w+", encoding="utf-8", dir=dir
    ) as tempf:
        tempf.write(config)
        tempf.flush()
        name = tempf.name

    print(name)

    os.environ["NASTOOL_CONFIG"] = tempf.name

    cmd = [sys.executable, os.path.join("src", "run.py")]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        sys.exit(0)
    finally:
        shutil.rmtree(dir)
