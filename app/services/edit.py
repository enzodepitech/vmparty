import asyncio
import json
from fastapi import WebSocket

async def run_ansible_edit(
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
    extra_vars = {
        "target_vmid": vmid,
        "new_team_name": new_team_name,
        "students_to_add": students_to_add,
        "students_to_remove": students_to_remove
    }

    try:
        await websocket.send_text(f"Playing Ansible for VM '{vmid}'...")
        await websocket.send_text(f"Change VM Name to '{new_team_name}'...")
        await websocket.send_text(f"Adding students: {students_to_add}")
        await websocket.send_text(f"Removing students: {students_to_remove}")

        process = await asyncio.create_subprocess_exec(
            "ansible-playbook", 
            "03_edit.yml", 
            "-e", json.dumps(extra_vars),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        while True:
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
