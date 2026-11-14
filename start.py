import subprocess
import sys
import time

def run_migrations_and_start_server():
    print("=" * 60)
    print("🚀 MEDTATVAA ABDM GATEWAY CONTAINER INITIALIZING")
    print("=" * 60)

    # 1. Run Alembic Database Migrations
    print("\n[1/2] Running automated database migrations (Alembic)...")
    try:
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        print("✅ Database migrations applied successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Migration failed with error code: {e.returncode}")
        sys.exit(1)

    # 2. Launch Uvicorn Server
    print("\n[2/2] Starting Uvicorn API server on 0.0.0.0:8000...")
    try:
        subprocess.run([
            "uvicorn", "app.main:app", 
            "--host", "0.0.0.0", 
            "--port", "8000"
        ], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Gateway container shutting down cleanly.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Server exited with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migrations_and_start_server()