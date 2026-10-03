"""Create a private local demo env; never overwrite or print credentials."""
import argparse
import os
from pathlib import Path
import secrets


def configure(output, port=8080):
    if not 1024 <= port <= 65535:
        raise ValueError("port must be 1024..65535")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f"NEO4J_PASSWORD={secrets.token_hex(24)}\nDEMO_PORT={port}\nDEMO_BIND_ADDRESS=127.0.0.1\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("deploy/demo.env"))
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    try:
        configure(args.output, args.port)
    except (OSError, ValueError) as exc:
        parser.error(f"configuration not created ({type(exc).__name__}); existing credentials were not changed")
    print(f"Created private config: {args.output}; loopback port {args.port}; credentials not printed")


if __name__ == "__main__":
    main()
