import os
import yaml
import secrets
import logging
from requests.exceptions import HTTPError, RequestException

from fastapi import WebSocket

from guacapy import Guacamole
from guacapy.managers import ConnectionManager, UserManager

from copy import deepcopy

GUACAMOLE_URL = os.getenv("GUACAMOLE_URL", "")
GUAC_ADMIN_USER = os.getenv("GUACAMOLE_API_USER", "")
GUAC_ADMIN_PASS = os.getenv("GUACAMOLE_API_PASSWORD", "")
DATABASE_SOURCE = "postgresql"

USER_PAYLOAD_TEMPLATE = {
    "username": "",
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

def sanitize_email_to_username(email: str) -> str:
    """
    Modify email to make it POSIX friendly
    """
    return email.split("@")[0].replace(".", "_")

async def update_guacamole_resources(websocket: WebSocket,
                                     connection_id: str,
                                     new_team_name: str,
                                     add_emails: list[str],
                                     remove_emails: list[str]
                                     ) -> None:
    """
    """
    try:
        guac = Guacamole(GUACAMOLE_URL, username=GUAC_ADMIN_USER, password=GUAC_ADMIN_PASS)

        # -------------------------------------------------------------
        # Rename guacamole connection
        # -------------------------------------------------------------
        connection = guac.connections.details(connection_id)
        if connection.get("name") != new_team_name:
            renamed_connection = deepcopy(connection)
            renamed_connection["name"] = new_team_name
            try:
                guac.connections.update(connection_id, renamed_connection)
            except ValueError:
                await websocket.send_text(f"Error when rename connection, invalid payload: {renamed_connection}")

        # -------------------------------------------------------------
        # Remove access to deleted students
        # -------------------------------------------------------------
        for email in remove_emails:
            if not email:
                continue
            try:
                guac.connections.revoke_connection(
                    username=email,
                    connection_id=connection_id,
                    permission="READ"
                )
            except HTTPError as e:
                if e.response.status_code != 404:
                    raise e

        # -------------------------------------------------------------
        # Create new student connection and access
        # -------------------------------------------------------------
        for email in add_emails:
            if not email:
                continue

            # Create guacamole user if doesn't exist
            try:
                guac.users.user_details(email)
            except HTTPError as e:
                if e.response.status_code == 404:
                    new_user = deepcopy(USER_PAYLOAD_TEMPLATE)
                    new_user["username"] = email
                    guac.users.create(new_user)
                else:
                    raise e

            # Assign connection
            guac.users.assign_connection(
                username=email,
                permission="READ",
                connection_id=connection_id,
            )
    except HTTPError as http_err:
        status = http_err.response.status_code
        error_msg = http_err.response.text
        raise RuntimeError(f"Guacamole API Error ({status}): {error_msg}") from http_err
    except RequestException as req_err:
        raise RuntimeError(f"Impossible to connect to Guacamole server: {str(req_err)}") from req_err

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
                raise ValueError("Student mail must have one @.")
                

            connection_name = f"{vm_name}: ({student_username})"
            connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
            connection_payload.update({
                "name": connection_name,
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
            except TypeError as e:
                await websocket.send_text(f"Connection already exists, trying to fetch it...")
                connection = guac.connections.get_by_name(connection_name)
                await websocket.send_text(f"Connection: {connection}")

                # Retrieve information
                conn_id = connection["identifier"]
                password = connection["parameters"]["password"]
                student_username = connection["parameters"]["username"]
                vm_ip = connection["parameters"]["hostname"]
                    
                await websocket.send_text(f"Successfully retrieved connection.")

            try:
                user_payload = deepcopy(USER_PAYLOAD_TEMPLATE)
                user_payload["username"] = student_mail
                guac.users.create(user_payload)
            except HTTPError as e:
                status_code = e.response.status_code
                if status_code == 400:
                    await websocket.send_text(f"User {student_mail} already exists.")
                else:
                    raise

            # Assign connection permission to the user
            try:
                guac.users.assign_connection(
                    username=student_mail,
                    permission="READ",
                    connection_id=conn_id,
                )
                await websocket.send_text(f"Successfully granted student '{student_mail}:{student_username}' access to '{vm_name}'")
            except HTTPError as e:
                status_code = e.response.status_code
                if status_code == 500:
                    await websocket.send_text(f"Connection already assigned for '{student_mail}'")
                else:
                    raise

            credentials_list.append({
                "vmid": vm["vmid"],
                "username": student_username,
                "password": password
            })

    os.makedirs(os.path.dirname("storage/exports"), exist_ok=True)
    with open("storage/exports/credentials.yml", "w") as out_file:
        yaml.dump({"student_credentials": credentials_list}, out_file, default_flow_style=False)
        await websocket.send_text("--- Guacamole successfully configured for all students! ---")

