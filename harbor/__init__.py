
import subprocess
import sys

def main():
    subprocess.run(["bash", "harbor.sh"] + sys.argv[1:], check=True)

if __name__ == "__main__":
    main()