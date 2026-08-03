import os
import yaml
import secrets
import logging

from fastapi import WebSocket

from guacapy import Guacamole
from guacapy.managers import ConnectionManager, UserManager

from requests.exceptions import HTTPError, ConnectionError, RequestException

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
            student_mail = student
            student_username = student_mail
            try:
                student_username = student_mail.split('@')[0].replace('.', '_')
            except Exception as e:
                logging.error(f"Error when sanitizing student mail: {str(e)}");
                await websocket.send_text(f"Error when sanitizing student mail: {str(e)}")
                

            connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
            connection_payload.update({
                "name": f"{vm_name}: ({student_username})",
                "parameters": {
                    "hostname": vm_ip,
                    "username": student_username,
                    "password": password
                }
            })

            conn_id = None
            try:
                connection = guac.connections.create(connection_payload)
                conn_id = connection["identifier"]
                await websocket.send_text(f"Successfully created connection: '{vm_name}' (ID: {conn_id})")
                logging.info(f"Successfully created connection: '{vm_name}' (ID: {conn_id})");
            except HTTPError as e:
                status_code = e.response.status_code
                if status_code == 400:
                    await websocket.send_text(f"Connection alreay existing, trying to fetch it...")
                    connection = guac.connections.get_by_name()
                    conn_id = connection["identifier"]
                    await websocket.send_text(f"Successfully retrieved connection.")
                else:
                    await websocket.send_text(f"Error when creating connection: {str(e)}")
            except Exception as e:
                await websocket.send_text(f"Error when creating connection: {str(e)}")
                logging.error(f"Error when creating connection: {str(e)}");

            try:
                user_payload = {
                    "username": student_mail,
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
                await websocket.send_text(f"Student payload: {user_payload}")
                guac.users.create(user_payload)
            except Exception as e:
                # User already exists
                await websocket.send_text(f"Error when creating {student_mail} user: {str(e)}")
                pass

            # Assign connection permission to the user
            try:
                guac.users.assign_connection(
                    username=student_mail,
                    permission="READ",
                    connection_id=conn_id,
                )
                await websocket.send_text(f"Successfully granted student '{student_mail}:{student_username}' access to '{vm_name}'")
            except Exception as e:
                await websocket.send_text(f"Error when assigning connection for '{student_mail}:{student_username}': {str(e)}")

            credentials_list.append({
                "vmid": vm["vmid"],
                "username": student_username,
                "password": password
            })

    os.makedirs(os.path.dirname("storage/exports"), exist_ok=True)
    with open("storage/exports/credentials.yml", "w") as out_file:
        yaml.dump({"student_credentials": credentials_list}, out_file, default_flow_style=False)
        await websocket.send_text("--- Guacamole successfully configured for all students! ---")

