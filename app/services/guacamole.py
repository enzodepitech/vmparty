import os
import yaml
import secrets

from fastapi import WebSocket

from guacapy import Guacamole
from guacapy.managers import ConnectionManager, UserManager

from copy import deepcopy

GUACAMOLE_URL = os.getenv("GUACAMOLE_URL", "")
GUAC_ADMIN_USER = os.getenv("GUACAMOLE_API_USER", "")
GUAC_ADMIN_PASS = os.getenv("GUACAMOLE_API_PASSWORD", "")
DATABASE_SOURCE = "postgresql"

async def register_guacamole_access(websocket: WebSocket, vars_file_path: str):
    """Synchronous execution block using guacapy."""
    # Parse Ansible vars file
    with open(vars_file_path, "r") as f:
        data = yaml.safe_load(f)
        vms = data.get("vms", [])

    if not vms:
        await websocket.send_text("Error: No VMs found in vars file to register with Guacamole.")
        return

    # Authenticate to Guacamole REST API via admin account
    guac = Guacamole(
        hostname=GUACAMOLE_URL,
        username=GUAC_ADMIN_USER,
        password=GUAC_ADMIN_PASS
    )

    await websocket.send_text("Successfully connected to guacamole.")

    credentials_list = []
    
    # Process each deployed VM/LXC container
    for vm in vms:
        vm_name = vm["name"]
        vm_ip = vm["ip"]
        students = vm.get("students", [])

        # Assign access to students
        for student in students:
            password = secrets.token_urlsafe(12)

            connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
            connection_payload.update({
                "name": vm_name,
                "parameters": {
                    "hostname": vm_ip,
                    "username": student,
                    "password": password
                }
            })

            connection = guac.connections.create(connection_payload)
            conn_id = connection["identifier"]
            await websocket.send_text(f"Created Guacamole SSH Connection: '{vm_name}' (ID: {conn_id})")
            
            try:
                user_payload = {
                    "username": student,
                    "password": "",
                    "attributes": {
                        "disabled": "",
                        "expired": "",
                        "access-window-start": "",
                        "access-window-end": "",
                        "valid-from": "",
                        "valid-until": "",
                        "timezone": None,
                        "guac-full-name": "",
                        "guac-organization": "",
                        "guac-organizational-role": "",
                        "guac-email-address": "",
                    },
                }
                guac.users.create(user_payload)
            except Exception as e:
                # User already exists
                await websocket.send_text(f"Error when creating {student} user: {str(e)}")
                pass

            # Assign connection permission to the user
            guac.users.assign_connection(
                username=student,
                permission="READ",
                connection_id=conn_id,
            )
            await websocket.send_text(f"Granted student '{student}' access to '{vm_name}'")

            credentials_list.append({
                "vmid": vm_ip,
                "username": student,
                "password": password
            })

    os.makedirs(os.path.dirname("storage/exports"), exist_ok=True)
    with open("storage/exports/credentials.yml", "w") as out_file:
        yaml.dump({"student_credentials": credentials_list}, out_file, default_flow_style=False)
        await websocket.send_text("--- Guacamole successfully configured for all students! ---")

