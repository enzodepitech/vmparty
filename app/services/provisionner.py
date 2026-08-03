from fastapi import WebSocket, WebSocketDisconnect, Depends

import logging
import asyncio
import os

from app.auth import require_admin_ws

async def provide_student_credentials(websocket: WebSocket, admin_user: str = Depends(require_admin_ws)):
    """
    """
    await websocket.send_text("--- Starting Credentials Provisionning ---")

    # Deploy VMs via Ansible
    playbook_cmd = [
        "ansible-playbook",
        "ansible/02_provider.yml",
        "-i", "../storage/exports/inventory.ini",
        "--private-key", "/app/keys/id_ed25519",
        "-e",
        "@storage/exports/credentials.yml"
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = await asyncio.create_subprocess_exec(
            *playbook_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        await websocket.send_text("--- Starting Ansible Deployment ---")

        # Stream logs line-by-line in real time
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text("--- Student Credentials Deployment Finished Successfully ---")
        else:
            await websocket.send_text(f"--- Deployment Failed (Exit Code {process.returncode}) ---")

    except WebSocketDisconnect:
        logging.info("Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"Error executing playbook: {str(e)}")
