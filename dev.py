#!/usr/bin/env python3
"""
dev.py - Task runner for Order Service.

Works on Windows, Linux and macOS without any extra dependencies.
Automatically creates the virtual environment and installs dependencies
if needed. No manual venv activation required.

Usage:
    python dev.py help
    python dev.py up
    python dev.py test
"""

import subprocess
import sys
import os
import json
import time
from pathlib import Path

# -----------------------------------------------------------------------------
# Venv paths
# -----------------------------------------------------------------------------

VENV_DIR = Path(".venv")


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_pip() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def _venv_pytest() -> str:
    if sys.platform == "win32":
        return str((VENV_DIR / "Scripts" / "pytest.exe").resolve())
    return str((VENV_DIR / "bin" / "pytest").resolve())


def _ensure_venv() -> None:
    """Creates venv and installs dependencies if .venv does not exist."""
    if _venv_python().exists():
        return
    print("Virtual environment not found. Creating .venv...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print("Installing dependencies...")
    subprocess.run(
        [str(_venv_pip()), "install", "-e", ".[dev]", "--quiet"],
        check=True,
    )
    print("Environment ready.\n")


_ensure_venv()

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def run(cmd: str, check: bool = True) -> None:
    """Runs a shell command, printing it before executing."""
    print("\n$ " + cmd)
    subprocess.run(cmd, shell=True, check=check)


def run_pytest(args: str, check: bool = True) -> None:
    """
    Runs pytest using the venv executable directly.
    This avoids relying on pytest being in the system PATH,
    which is unreliable on Windows even with an active venv.
    """
    cmd = _venv_pytest() + " " + args
    print("\n$ " + cmd)
    subprocess.run(cmd, shell=True, check=check)


def _http_post(url: str, payload: dict, correlation_id: str | None = None) -> tuple[int, dict]:
    """
    Makes a POST request using only stdlib.
    Avoids curl so smoke tests work on Windows without quoting issues.
    """
    import urllib.request
    import urllib.error

    headers = {"Content-Type": "application/json"}
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------


def help() -> None:
    print("")
    print("Order Service - Task Runner")
    print("")
    print("Environment")
    print("  python dev.py up                Start all services + run migrations")
    print("  python dev.py down              Stop and remove all containers")
    print("  python dev.py build             Rebuild Docker images")
    print("  python dev.py restart           Rebuild and restart all services")
    print("  python dev.py logs              Follow logs from api and worker")
    print("  python dev.py migrate           Run Alembic migrations")
    print("")
    print("Tests")
    print("  python dev.py test              Full test suite with coverage")
    print("  python dev.py test-unit         Unit tests only (no Docker required)")
    print("  python dev.py test-repositories Repository tests (requires Docker)")
    print("  python dev.py test-integration  Integration tests (requires Docker)")
    print("  python dev.py test-coverage     Generate HTML coverage report")
    print("")
    print("Smoke tests")
    print("  python dev.py orders            Run HTTP smoke tests against the API")
    print("  python dev.py sqs-messages      Read messages from the main SQS queue")
    print("  python dev.py sqs-dlq           Read messages from the Dead Letter Queue")
    print("")


def _wait_for_api(timeout: int = 60) -> bool:
    """Polls /health until the API is ready or timeout is reached."""
    import urllib.request
    deadline = time.time() + timeout
    print("\nWaiting for API to be ready...", end="", flush=True)
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            print(" ready!")
            return True
        except Exception:
            print(".", end="", flush=True)
            time.sleep(2)
    print(" timed out!")
    return False


def up() -> None:
    run("docker compose up --build -d")
    _wait_for_api()
    print("")
    print("Environment ready:")
    print("  API:             http://localhost:8000")
    print("  Swagger UI:      http://localhost:8000/docs")
    print("  Metrics:         http://localhost:8000/metrics")
    print("  Requester mock:  http://localhost:8001")
    print("  LocalStack:      http://localhost:4566")
    print("")


def down() -> None:
    run("docker compose down -v")


def build() -> None:
    run("docker compose build")


def restart() -> None:
    down()
    up()


def logs() -> None:
    # stderr=DEVNULL suppresses OTel spans (written to stderr),
    # showing only structured JSON application logs.
    cmd = "docker compose logs -f fastapi-service worker"
    print("\n$ " + cmd)
    subprocess.run(cmd, shell=True, stderr=subprocess.DEVNULL)


def migrate() -> None:
    run("docker compose exec fastapi-service alembic upgrade head")


def test() -> None:
    run_pytest("--cov=app --cov-report=term-missing -v")


def test_unit() -> None:
    run_pytest(
        "tests/unit/test_order_service.py "
        "tests/unit/test_requester_client.py "
        "tests/unit/test_worker.py -v"
    )


def test_repositories() -> None:
    run_pytest("tests/unit/test_repositories.py -v")


def test_integration() -> None:
    run_pytest("tests/integration -v")


def test_coverage() -> None:
    run_pytest("--cov=app --cov-report=html -v")
    report = os.path.abspath("htmlcov/index.html")
    print("\nReport generated at " + report)
    if sys.platform == "win32":
        os.startfile(report)
    elif sys.platform == "darwin":
        run("open " + report, check=False)
    else:
        run("xdg-open " + report, check=False)


def orders() -> None:
    base = "http://localhost:8000/orders"

    print("\n--- Creating order ORD-001 ---")
    status, body = _http_post(base, {
        "external_order_id": "ORD-001",
        "requester_id": "REQ-001",
        "description": "Manutencao preventiva",
    })
    print("HTTP " + str(status))
    print(json.dumps(body, indent=2, ensure_ascii=False))

    print("\n--- Idempotency check (same ORD-001, expect HTTP 200) ---")
    status, body = _http_post(base, {
        "external_order_id": "ORD-001",
        "requester_id": "REQ-001",
        "description": "Manutencao preventiva",
    })
    print("HTTP " + str(status))
    print(json.dumps(body, indent=2, ensure_ascii=False))

    print("\n--- Requester not found (expect HTTP 422) ---")
    status, body = _http_post(base, {
        "external_order_id": "ORD-002",
        "requester_id": "NOT-FOUND",
        "description": "Teste",
    })
    print("HTTP " + str(status))
    print(json.dumps(body, indent=2, ensure_ascii=False))

    print("\n--- Service unavailable (expect HTTP 503) ---")
    status, body = _http_post(base, {
        "external_order_id": "ORD-003",
        "requester_id": "ERROR",
        "description": "Teste",
    })
    print("HTTP " + str(status))
    print(json.dumps(body, indent=2, ensure_ascii=False))


def sqs_messages() -> None:
    run(
        "aws --endpoint-url=http://localhost:4566 sqs receive-message "
        "--queue-url http://localhost:4566/000000000000/orders-queue "
        "--region us-east-1",
        check=False,
    )


def sqs_dlq() -> None:
    run(
        "aws --endpoint-url=http://localhost:4566 sqs receive-message "
        "--queue-url http://localhost:4566/000000000000/orders-dlq "
        "--region us-east-1",
        check=False,
    )


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

COMMANDS = {
    "help": help,
    "up": up,
    "down": down,
    "build": build,
    "restart": restart,
    "logs": logs,
    "migrate": migrate,
    "test": test,
    "test-unit": test_unit,
    "test-repositories": test_repositories,
    "test-integration": test_integration,
    "test-coverage": test_coverage,
    "orders": orders,
    "sqs-messages": sqs_messages,
    "sqs-dlq": sqs_dlq,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    fn = COMMANDS.get(cmd)
    if fn is None:
        print("Unknown command: " + cmd)
        help()
        sys.exit(1)
    fn()
