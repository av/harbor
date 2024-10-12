
import os
import subprocess
import sys

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    harbor_sh_path = os.path.join(parent_dir, "harbor.sh")

    result = subprocess.run(
        ["bash", harbor_sh_path] + sys.argv[1:],
        shell=False,
        text=True,
        check=False,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()