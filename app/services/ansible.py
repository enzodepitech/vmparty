import asyncio
import json
import os
import logging

from fastapi import WebSocket, WebSocketDisconnect

from sqlalchemy.orm import Session

from app.core.utils import sanitize_email_to_username, DEFAULT_USERNAME, slugify
import app.database as db

async def run_delete(db_session: Session, websocket: WebSocket, id):
    vm_data = db.get_vm_byid(db_session, id)
    if not vm_data:
        return
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_data.pve_id,
        "vm_ip": vm_data.ip,
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

        await websocket.send_text(f"[DELETE] Deleting VM '{vm_data.pve_id}:{vm_data.name}({vm_data.ip})'...")

        while True and process.stdout is not None:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text(f"[DELETE] Successfully deleted VM '{vm_data.pve_id}:{vm_data.name}'.")
        else:
            await websocket.send_text(f"[DELETE] Deployment Failed (Exit Code {process.returncode})")

    except WebSocketDisconnect:
        logging.info("[DELETE] Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"[DELETE] Error executing playbook: {str(e)}")
        raise

async def run_edit(
    db_session: Session,
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
        user_data = db.get_user(db_session, student_mail)
        if not user_data:
            return False
        students_to_add_config.append({
            "username": user_data.username,
            "password": user_data.password
        })

    students_to_remove_config = []
    for student_mail in students_to_remove:
        user_data = db.get_user(db_session, student_mail)
        if not user_data:
            return False
        students_to_remove_config.append({
            "username": user_data.username
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

async def run_provide_container(db_session: Session, websocket: WebSocket, vm_id):
    await run_provide(db_session, websocket, vm_id, "ansible/01_provider.yml")

async def run_provide_vm(db_session: Session, websocket: WebSocket, vm_id):
    await run_provide(db_session, websocket, vm_id, "ansible/01_provider_vm.yml")
    
async def run_provide(db_session: Session, websocket: WebSocket, vm_id: int, ansible_playbook_path: str):
    vm_data = db.get_vm(db_session, vm_id)
    if not vm_data:
        logging.error(f"No vm corresponding with id {vm_id}.")
        return False
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_data.pve_id,
        "vm_name": vm_data.name,
        "ip": vm_data.ip
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

        await websocket.send_text(f"[PROVIDE] Starting Ansible Providing '{vm_id}:{vm_data.name}({vm_data.ip})'...")

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

async def run_provision(db_session: Session, websocket: WebSocket, vm_id: int, single_user: bool):
    """
    """
    await websocket.send_text("[PROVISION] Provisionning VM...")

    vm_data = db.get_vm(db_session, vm_id)
    if not vm_data:
        logging.error(f"No VM matches with the id {vm_id}")
        return

    student_credentials = []

    if single_user:
        vm_name = slugify(vm_data.name)
        user_data = db.get_user(db_session, vm_name)
        if not user_data:
            logging.error(f"No user matches with name: {vm_name}")
        student_credentials.append({
            "username": vm_data.username,
            "password": vm_data.password
        })
    else:
        for user in list(vm_data.users):
            student_credentials.append({
                "username": user.username,
                "password": user.password
            })
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_id,
        "vm_ip": vm_data.ip,
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
        
