import argparse
import uvicorn
from broker.app import create_app

parser = argparse.ArgumentParser()
parser.add_argument("--config", default=".runtime/config.json")
parser.add_argument("--port", type=int, default=4302)
args = parser.parse_args()
uvicorn.run(create_app(args.config), host="127.0.0.1", port=args.port, log_level="warning")
