#!/usr/bin/env python3
"""
Unified entry point for KidSearch Dashboard and API
Supports Docker deployment with flexible service configuration
"""

import os
import sys
import argparse
import logging
import subprocess
import signal
from pathlib import Path
from typing import List, Optional, Dict
from dotenv import load_dotenv

# Add project root to sys.path for module resolution
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
load_dotenv()

# Setup logging
# Get log level from env var, default to INFO
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level_str,
    format="[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
)
logger = logging.getLogger(__name__)


class ServiceManager:
    """Manages Dashboard and API services."""

    def __init__(self):
        self.services: Dict[int, Dict[str, any]] = {}  # pid -> {process: Popen, name: str}
        self.setup_signal_handlers()

    def setup_signal_handlers(self):
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

    def handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"\nReceived signal {signum}, shutting down gracefully...")
        self.stop_all()
        sys.exit(0)

    def _get_display_url(self, service_type: str, host: str, port: int) -> str:
        """
        Constructs the display URL based on DISPLAY_HOST variables.
        """
        display_host_var = f"{service_type.upper()}_DISPLAY_HOST"
        display_host = os.getenv(display_host_var) or os.getenv("DISPLAY_HOST")

        if display_host:
            # Ensure no protocol is in the env var, strip if present
            display_host = display_host.replace("https://", "").replace("http://", "")
            # If a public domain is provided, use HTTPS and no port
            return f"https://{display_host}"
        else:
            # Otherwise, construct a local URL for development
            local_host = "localhost" if host == "0.0.0.0" else host
            return f"http://{local_host}:{port}"

    def start_dashboard(self, port: int = 8501, host: str = "0.0.0.0"):
        """
        Start the Streamlit dashboard.
        The PYTHONPATH is explicitly set for the subprocess to ensure module discovery.
        """
        dashboard_path = Path(__file__).parent / "dashboard" / "Home.py"

        if not dashboard_path.exists():
            logger.error(f"Dashboard file not found: {dashboard_path}")
            return None

        display_url = self._get_display_url("dashboard", host, port)
        # Streamlit's --browser.serverAddress expects a hostname, not a full URL
        display_hostname_only = display_url.replace("https://", "").replace("http://", "").split(":")[0]

        logger.info(f"Starting Dashboard (listening on {host}:{port}, accessible at {display_url})...")

        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard_path),
            "--server.port", str(port),
            "--server.address", host,
            "--browser.serverAddress", display_hostname_only,  # Indique à Streamlit quelle URL afficher
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ]

        # Add environment variables for subprocesses
        env = os.environ.copy()
        # Ensure project root is in PYTHONPATH for subprocesses
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        # Force CPU for PyTorch
        env["CUDA_VISIBLE_DEVICES"] = "-1"

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )
            self.services[process.pid] = {"process": process, "name": "DASHBOARD"}            

            logger.info(f"✓ Dashboard started (PID: {process.pid})")
            logger.info(f"  Access at: {display_url}")
            return process
        except Exception as e:
            logger.error(f"✗ Failed to start Dashboard: {e}")
            return None

    def start_api(self, port: int = 8080, host: str = "0.0.0.0", workers: int = 4):
        """
        Start the FastAPI backend.
        The PYTHONPATH is explicitly set for the subprocess to ensure module discovery.
        """
        api_enabled = os.getenv("API_ENABLED", "false").lower() == "true"

        if not api_enabled:
            logger.warning("API is disabled. Set API_ENABLED=true in .env to enable.")
            return None

        # Check if FastAPI is installed
        try:
            import fastapi
            import uvicorn
        except ImportError:
            logger.error(
                "FastAPI dependencies not installed. "
                "Run: pip install -r requirements.txt"
            )
            return None

        display_url = self._get_display_url("api", host, port)
        
        # Get log level for Uvicorn from env var
        log_level = os.getenv("LOG_LEVEL", "info").lower()

        logger.info(f"Starting API with {workers} workers (listening on {host}:{port}, accessible at {display_url})...")

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "meilisearchcrawler.api.server:app",
            "--host", host,
            "--port", str(port),
            "--workers", str(workers),
            "--log-level", log_level,
            "--lifespan", "on",  # Gère le lifespan dans le process parent
        ]

        # Add environment variables for subprocesses
        env = os.environ.copy()
        # Ensure project root is in PYTHONPATH for subprocesses
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        # Force CPU for PyTorch
        env["CUDA_VISIBLE_DEVICES"] = "-1"

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )
            self.services[process.pid] = {"process": process, "name": "API"}            

            logger.info(f"✓ API started (PID: {process.pid})")
            logger.info(f"  Swagger UI: {display_url}/api/docs")
            logger.info(f"  ReDoc:      {display_url}/api/redoc")
            return process
        except Exception as e:
            logger.error(f"✗ Failed to start API: {e}")
            return None

    def monitor_processes(self):
        """Monitor running processes and print their output."""
        import select
        from datetime import datetime

        # Collect all process outputs
        streams = {
            info["process"].stdout.fileno(): info["process"]
            for info in self.services.values()
            if info["process"].stdout
        }

        while self.services:
            # Check if any process has terminated
            terminated_pids = []
            for pid, info in self.services.items():
                proc = info["process"]
                if proc.poll() is not None:
                    logger.warning(f"[{info['name']}] Process {pid} terminated with code {proc.returncode}")
                    terminated_pids.append(pid)
            
            for pid in terminated_pids:
                del self.services[pid]
                if streams.get(pid):
                    del streams[pid]

            if not self.services:
                break

            # Read available output (non-blocking)
            if streams:
                readable, _, _ = select.select(list(streams.keys()), [], [], 0.1)
                for fd in readable:
                    proc = streams[fd]
                    line = proc.stdout.readline()
                    if line:
                        service_name = self.services.get(proc.pid, {}).get("name", f"PID:{proc.pid}")
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
                        print(f"{timestamp} - [{service_name}] - {line.rstrip()}")

    def stop_all(self):
        """Stop all running processes."""
        if not self.services:
            return

        logger.info("Stopping all services...")

        for info in self.services.values():
            process = info["process"]
            try:
                process.terminate()
                process.wait(timeout=5)
                logger.info(f"✓ Process {process.pid} stopped")
            except subprocess.TimeoutExpired:
                logger.warning(f"Force killing process {process.pid}")
                process.kill()
                process.wait()
            except Exception as e:
                logger.error(f"Error stopping process {process.pid}: {e}")

        self.services.clear()
        logger.info("All services stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="KidSearch Dashboard & API Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start both Dashboard and API
  python start.py --all

  # Start only Dashboard
  python start.py --dashboard

  # Start only API
  python start.py --api

  # Custom ports
  python start.py --all --dashboard-port 8502 --api-port 8081

  # Docker mode (respects environment variables)
  python start.py --docker
        """,
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Start both Dashboard and API",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start Dashboard only",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Start API only",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Docker mode: read SERVICE env var (dashboard|api|all)",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=int(os.getenv("DASHBOARD_PORT", "8501")),
        help="Dashboard port (default: 8501)",
    )
    parser.add_argument(
        "--dashboard-host",
        default=os.getenv("DASHBOARD_HOST", "0.0.0.0"),
        help="Dashboard host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=int(os.getenv("API_PORT", "8080")),
        help="API port (default: 8080)",
    )
    parser.add_argument(
        "--api-host",
        default=os.getenv("API_HOST", "0.0.0.0"),
        help="API host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--api-workers",
        type=int,
        default=int(os.getenv("API_WORKERS", "4")),
        help="API workers (default: 4)",
    )

    args = parser.parse_args()

    # Docker mode: read SERVICE environment variable
    if args.docker:
        service = os.getenv("SERVICE", "all").lower()
        args.all = service == "all"
        args.dashboard = service == "dashboard" or args.all
        args.api = service == "api" or args.all
        logger.info(f"Docker mode: SERVICE={service}")

    # Default: start all if no specific service selected
    if not (args.dashboard or args.api):
        args.all = True
        args.dashboard = True
        args.api = True

    # Print banner
    banner = """
    ┌──────────────────────────────────────────────────────────┐
    │  🕸️   KidSearch - Unified Dashboard & API Manager   🚀  │
    └──────────────────────────────────────────────────────────┘
    """
    print(banner)

    manager = ServiceManager()

    # Start requested services
    started_any = False

    if args.dashboard:
        if manager.start_dashboard(args.dashboard_port, args.dashboard_host):
            started_any = True

    if args.api:
        if manager.start_api(args.api_port, args.api_host, args.api_workers):
            started_any = True

    if not started_any:
        logger.error("No services started. Exiting.")
        sys.exit(1)

    print("\n" + "─" * 60)
    logger.info("✅ All services are running. Press Ctrl+C to shut down.")
    print("─" * 60 + "\n")

    # Monitor processes
    try:
        manager.monitor_processes()
    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
    finally:
        manager.stop_all()


if __name__ == "__main__":
    main()
