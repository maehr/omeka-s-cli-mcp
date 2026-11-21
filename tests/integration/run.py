"""Install Omeka S and run tests against the local Compose project."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx2

_COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(Path(__file__).with_name("compose.yml").resolve()),
    "--project-name",
    f"omeka-client-{secrets.token_hex(4)}",
]


def compose(*args: str) -> str:
    return subprocess.check_output([*_COMPOSE, *args], text=True).strip()


def install(url: str) -> None:
    email = "tester@example.org"
    password = "Disposable-Pass-37!"
    form = {
        "user[email]": email,
        "user[email-confirm]": email,
        "user[name]": "Integration test",
        "user[password-confirm][password]": password,
        "user[password-confirm][password-confirm]": password,
        "settings[installation_title]": "Disposable Omeka",
        "settings[time_zone]": "UTC",
        "settings[locale]": "",
    }
    with httpx2.Client(trust_env=False, timeout=20) as client:
        for _ in range(30):
            try:
                response = client.get(url + "/install")
                if response.status_code == 200:
                    break
            except httpx2.RequestError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("The disposable install form is unavailable.")
        response = client.post(url + "/install", data=form)
        if not response.headers.get("location", "").endswith("/login"):
            raise RuntimeError(
                f"Omeka installation did not reach login (HTTP {response.status_code})."
            )


def main() -> int:
    """Run the integration tests and remove the disposable containers."""
    try:
        subprocess.run([*_COMPOSE, "up", "--build", "-d"], check=True)
        bind = compose("port", "omeka", "80")
        if not bind.startswith("127.0.0.1:"):
            raise RuntimeError("The Omeka instance must bind to loopback.")
        url = f"http://{bind}/collection"
        install(url)
        identity = secrets.token_hex(16)
        credential = secrets.token_hex(16)
        credential_hash = compose(
            "exec",
            "-T",
            "omeka",
            "php",
            "-r",
            "echo password_hash($argv[1], PASSWORD_DEFAULT);",
            credential,
        )
        sql = (
            "INSERT INTO api_key (id, owner_id, label, credential_hash, created) "
            f"VALUES ('{identity}', 1, 'integration', '{credential_hash}', NOW());"
        )
        compose(
            "exec",
            "-T",
            "db",
            "mariadb",
            "-uomeka",
            "-pomeka-disposable",
            "omeka",
            "-e",
            sql,
        )
        return subprocess.call(
            [sys.executable, "-m", "pytest", "-m", "integration", "--no-cov", "tests/integration"],
            env={
                **os.environ,
                "OMEKA_IT_URL": url,
                "OMEKA_IT_KEY_IDENTITY": identity,
                "OMEKA_IT_KEY_CREDENTIAL": credential,
            },
        )
    finally:
        subprocess.run([*_COMPOSE, "down", "--timeout", "2"], check=True)


if __name__ == "__main__":
    sys.exit(main())
