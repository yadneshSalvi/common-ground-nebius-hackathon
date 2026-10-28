"""Entrypoint for an explicitly selected isolated local container profile."""
import argparse
import json
from pathlib import Path
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("owner", "broker"), required=True)
    parser.add_argument("--config", default="/config/service.json")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.kind == "owner":
        from owner_agent.app import create_app
    else:
        from broker.app import create_app
    uvicorn.run(create_app(config), host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
