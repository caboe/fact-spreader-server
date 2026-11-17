"""Static safety checks on docker-compose.yml (AGENTS.md image pins, no Docker socket)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> None:
    path = Path("docker-compose.yml")
    if not path.exists():
        path = Path("../docker-compose.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = data.get("services") or {}
    errors: list[str] = []
    for name, service in services.items():
        image = service.get("image")
        if image:
            if image.endswith(":latest"):
                errors.append(f"{name}: image uses :latest")
            last = image.rsplit("/", 1)[-1]
            if ":" not in last:
                errors.append(f"{name}: image {image!r} has no pinned tag")
        for volume in service.get("volumes") or []:
            text = str(volume)
            if "/var/run/docker.sock" in text:
                errors.append(f"{name}: mounts the Docker socket")
        if service.get("privileged"):
            errors.append(f"{name}: privileged container")
        if service.get("network_mode") == "host":
            errors.append(f"{name}: host network")
    lightrag = services.get("lightrag", {}).get("image", "")
    if lightrag != "ghcr.io/hkuds/lightrag:v1.5.0":
        errors.append(f"lightrag image must be pinned to v1.5.0, got {lightrag!r}")
    for name in ("backend", "worker"):
        build = services.get(name, {}).get("build") or {}
        if build.get("context") != "." or build.get("dockerfile") != "backend/Dockerfile":
            errors.append(f"{name}: expected root context and backend/Dockerfile")
    if errors:
        print("compose check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)
    print("compose check passed: images pinned, no Docker socket, no host network")


if __name__ == "__main__":
    main()
