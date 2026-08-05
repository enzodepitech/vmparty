import os
import logging
from requests.exceptions import HTTPError, RequestException

from fastapi import WebSocket

from guacapy import Guacamole
from guacapy.managers import ConnectionManager

from copy import deepcopy

from app.database import get_user, get_vm

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
                await websocket.send_text(f"[GUACAMOLE] Error when rename connection, invalid payload: {renamed_connection}")

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

async def register_one_guacamole_access(websocket: WebSocket, vm_id):
    # Authenticate to Guacamole REST API via admin account
    guac = Guacamole(
        hostname=GUACAMOLE_URL,
        username=GUAC_ADMIN_USER,
        password=GUAC_ADMIN_PASS
    )

    await websocket.send_text("[GUACAMOLE] Successfully connected to guacamole.")

    _, vm_ip, vm_name, students = get_vm(vm_id)

    for student in students.split(","):
        mail, username, hashed_password = get_user(student)
        
        connection_name = f"{vm_name}: ({username})"
        connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
        connection_payload.update({
            "name": connection_name,
            "parameters": {
                "hostname": vm_ip,
                "username": username,
                "password": hashed_password
            }
        })
        
        # Create guacamole connection
        try:
            connection = guac.connections.create(connection_payload)
            conn_id = connection["identifier"]
            await websocket.send_text(f"[GUACAMOLE] Successfully created connection: '{vm_name}' (ID: {conn_id})")
            logging.info(f"[GUACAMOLE] Successfully created connection: '{vm_name}' (ID: {conn_id})");
            
            # Create user in the database
        except TypeError as e:
            await websocket.send_text(f"[GUACAMOLE] Error: Connection already exists.")
            raise ValueError(f"Connection {vm_id} already exists in guacamole. Please delete it.")

        # Create guacamole user
        try:
            user_payload = deepcopy(USER_PAYLOAD_TEMPLATE)
            user_payload["username"] = mail
            guac.users.create(user_payload)
        except HTTPError as e:
            status_code = e.response.status_code
            if status_code == 400:
                await websocket.send_text(f"[GUACAMOLE] User {mail} already exists.")
            else:
                raise

        # Assign connection permission to the user
        try:
            guac.users.assign_connection(
                username=student,
                permission="READ",
                connection_id=conn_id,
            )
            await websocket.send_text(f"[GUACAMOLE] Successfully granted student '{mail}:{username}' access to '{vm_name}'")
        except HTTPError as e:
            status_code = e.response.status_code
            if status_code == 500:
                await websocket.send_text(f"[GUACAMOLE] Connection already assigned for '{mail}'")
            else:
                raise
