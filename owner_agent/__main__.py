import argparse
import json
from pathlib import Path
import uvicorn
from owner_agent.app import create_app

parser = argparse.ArgumentParser(description="Run one separately configured local owner agent")
parser.add_argument("--config", required=True, type=Path)
args = parser.parse_args()
config = json.loads(args.config.read_text())
uvicorn.run(create_app(config), host="127.0.0.1", port=config["port"], log_level="warning")
