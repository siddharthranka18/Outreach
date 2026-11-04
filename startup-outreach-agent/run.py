"""Root execution script for Startup Job Outreach Agent."""

from pathlib import Path
import sys

# Ensure 'src/' is available on the module search path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from startup_agent.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
