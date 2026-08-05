import asyncio
import json
import os
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.database import get_user, get_vm

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
        mail, username, hashed_password = get_user(student_mail)
        students_to_add_config.append({
            "username": username,
            "hashed_password": hashed_password
        })

    students_to_remove_config = []
    for student_mail in students_to_remove:
        mail, username, hashed_password = get_user(student_mail)
        students_to_remove_config.append({
            "username": username
        })
    
    extra_vars = {
        "target_vmid": vmid,
        "new_team_name": new_team_name,
        "students_to_add": students_to_add,
        "students_to_remove": students_to_remove
    }

    # Play ansible edit
    try:
        await websocket.send_text(f"Playing Ansible for VM '{vmid}'...")
        await websocket.send_text(f"Change VM Name to '{new_team_name}'...")
        await websocket.send_text(f"Adding students: {students_to_add_config}")
        await websocket.send_text(f"Removing students: {students_to_remove_config}")

        process = await asyncio.create_subprocess_exec(
            "ansible-playbook", 
            "ansible/03_edit.yml",
            "-i", "ansible/inventory.ini",
            "-e", json.dumps(extra_vars),
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
            await websocket.send_text("Successfully Updated VM via Ansible!")
            return True
        else:
            await websocket.send_text(f"Error - Ansible exited with code {process.returncode}.")
            return False

    except Exception as e:
        await websocket.send_text(f"Critical Error: {str(e)}")
        return False

async def run_provide(websocket: WebSocket, vm_id: int):
    _, vm_ip, vm_name, emails = get_vm(vm_id)
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_id,
        "name": vm_name,
        "ip": vm_ip,
        "students": emails
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = await asyncio.create_subprocess_exec(
            "ansible-playbook",
            "ansible/01_provider.yml",
            "-e", json.dumps(extra_vars),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        await websocket.send_text(f"Starting Ansible Providing '{vm_id}:{vm_name}({vm_ip})'...")

        while True and process.stdout is not None:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text(f"[ANSIBLE PROVIDE] Successfully provided VM.")
        else:
            await websocket.send_text(f"[ANSIBLE PROVIDE] Deployment Failed (Exit Code {process.returncode})")

    except WebSocketDisconnect:
        logging.info("Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"Error executing playbook: {str(e)}")
    finally:
        await websocket.close()

async def run_provision(websocket: WebSocket, vm_id):
    """
    """
    await websocket.send_text("--- Starting Credentials Provisionning ---")

    _, _, _, emails = get_vm(vm_id)
    
    student_credentials = []
    for email in emails:
        _, username, hashed_password = get_user(email)
        student_credentials.append({
            "username": username,
            "hashed_password": hashed_password
        })
    
    # Deploy VMs via Ansible
    extra_vars = {
        "vmid": vm_id,
        "student_credentials": student_credentials
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

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

        await websocket.send_text("--- Starting Ansible Deployment ---")

        # Stream logs line-by-line in real time
        while True and process.stdout is not None:
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
        
