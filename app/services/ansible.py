import asyncio
import json
import os
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.core.utils import sanitize_email_to_username, DEFAULT_USERNAME, slugify
import app.database as db

async def run_delete(websocket: WebSocket, id):
    vm_id, vm_ip, vm_name, _ = db.get_vm_byid(id)
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_id,
        "vm_ip": vm_ip,
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = await asyncio.create_subprocess_exec(
            "ansible-playbook",
            "ansible/04_delete.yml",
            "-vvv",
            "-e", json.dumps(extra_vars),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        await websocket.send_text(f"[DELETE] Deleting VM '{vm_id}:{vm_name}({vm_ip})'...")

        while True and process.stdout is not None:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text(f"[DELETE] Successfully deleted VM '{vm_id}:{vm_name}'.")
        else:
            await websocket.send_text(f"[DELETE] Deployment Failed (Exit Code {process.returncode})")

    except WebSocketDisconnect:
        logging.info("[DELETE] Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"[DELETE] Error executing playbook: {str(e)}")
        raise

async def run_edit(
    websocket: WebSocket,
    vmid: int,
    new_team_name: str,
    students_to_add: list,
    students_to_remove: list
) -> bool:
    """
    Exécute le playbook Ansible et stream les logs via WebSocket.
    Retourne True si le playbook réussit, False sinon.
    """
    # Configure ansible variables
    students_to_add_config = []
    for student_mail in students_to_add:
        _, username, password = db.get_user(student_mail)
        students_to_add_config.append({
            "username": username,
            "password": password
        })

    students_to_remove_config = []
    for student_mail in students_to_remove:
        _, username, hashed_password = db.get_user(student_mail)
        students_to_remove_config.append({
            "username": username
        })
    
    extra_vars = {
        "target_vmid": vmid,
        "new_team_name": new_team_name,
        "students_to_add": students_to_add_config,
        "students_to_remove": students_to_remove_config
    }

    # Play ansible edit
    try:
        await websocket.send_text(f"[EDIT] [ANSIBLE] Playing Ansible for VM '{vmid}'...")
        await websocket.send_text(f"[EDIT] [ANSIBLE] Change VM Name to '{new_team_name}'...")
        await websocket.send_text(f"[EDIT] [ANSIBLE] Adding students: {students_to_add_config}")
        await websocket.send_text(f"[EDIT] [ANSIBLE] Removing students: {students_to_remove_config}")

        # -l to not rename only play user changes
        process = await asyncio.create_subprocess_exec(
            "ansible-playbook", 
            "ansible/03_edit.yml",
            "-vvv",
            "-i", "ansible/inventory.ini",
            "-e", json.dumps(extra_vars),
            "-l", f"vm_{vmid}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        while True and process.stdout is not None:
            line = await process.stdout.readline()
            
            if not line:
                break # Fin du flux
                
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                await websocket.send_text(decoded_line)

        await process.wait()
        
        if process.returncode == 0:
            await websocket.send_text("[EDIT] Successfully Updated VM via Ansible!")
            return True
        else:
            await websocket.send_text(f"[EDIT] Error - Ansible exited with code {process.returncode}.")
            return False

    except Exception as e:
        await websocket.send_text(f"[EDIT] Critical Error: {str(e)}")
        return False

async def run_provide_container(websocket: WebSocket, vm_id):
    await run_provide(websocket, vm_id, "ansible/01_provider.yml")

async def run_provide_vm(websocket: WebSocket, vm_id):
    await run_provide(websocket, vm_id, "ansible/01_provider_vm.yml")
    
async def run_provide(websocket: WebSocket, vm_id: int, ansible_playbook_path: str):
    _, vm_ip, vm_name, emails = db.get_vm(vm_id)
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_id,
        "vm_name": vm_name,
        "ip": vm_ip,
        "students": emails
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = await asyncio.create_subprocess_exec(
            "ansible-playbook",
            ansible_playbook_path,
            "-vvv",
            "-e", json.dumps(extra_vars),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        await websocket.send_text(f"[PROVIDE] Starting Ansible Providing '{vm_id}:{vm_name}({vm_ip})'...")

        while True and process.stdout is not None:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text(f"[PROVIDE] Successfully provided VM.")
        else:
            await websocket.send_text(f"[PROVIDE] Deployment Failed (Exit Code {process.returncode})")

    except WebSocketDisconnect:
        logging.info("[PROVIDE] Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"[PROVIDE] Error executing playbook: {str(e)}")

async def run_provision(websocket: WebSocket, vm_id: int, single_user: bool):
    """
    """
    await websocket.send_text("[PROVISION] Provisionning VM...")

    _, vm_ip, vm_name, emails = db.get_vm(vm_id)

    student_credentials = []

    if single_user:
        _, username, password = db.get_user(slugify(vm_name))
        student_credentials.append({
            "username": username,
            "password": password
        })
    else:
        for email in emails.split(","):
            _, username, password = db.get_user(email)
            student_credentials.append({
                "username": username,
                "password": password
            })
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_id,
        "vm_ip": vm_ip,
        "student_credentials": student_credentials
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"

    try:
        process = await asyncio.create_subprocess_exec(
            "ansible-playbook",
            "ansible/02_provisioner.yml",
            "-i", "ansible/inventory.ini",
            "--private-key", "/root/.ssh/id_ed25519",
            "-e", json.dumps(extra_vars),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        await websocket.send_text("[PROVISION] Starting Ansible Provisionning...")

        # Stream logs line-by-line in real time
        while True and process.stdout is not None:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text("[PROVISION] Successfully provisioned VM.")
        else:
            await websocket.send_text(f"[PROVISION] Provision Failed (Exit Code {process.returncode}) ---")

    except WebSocketDisconnect:
        logging.info("[PROVISION] Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"[PROVISION] Error executing playbook: {str(e)}")
        
