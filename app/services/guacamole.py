import os
import logging
from requests.exceptions import HTTPError, RequestException

from app.core.utils import slugify
from fastapi import WebSocket

from guacapy import Guacamole
from guacapy.managers import ConnectionManager

from sqlalchemy.orm import Session

from copy import deepcopy

import app.database as db

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

# --------------------------------------------
# Edit guacamole
# --------------------------------------------

async def update_guacamole_resources(db_session: Session,
                                     websocket: WebSocket,
                                     connection_id: int,
                                     add_emails: list[str],
                                     remove_emails: list[str]
                                     ) -> None:
    """
    """
    try:
        guac = Guacamole(GUACAMOLE_URL, username=GUAC_ADMIN_USER, password=GUAC_ADMIN_PASS)

        await websocket.send_text(f"[EDIT] [GUACAMOLE] Successfully connected to Guacamole.")
        # -------------------------------------------------------------
        # Rename guacamole connection
        # -------------------------------------------------------------
        # Todo
        # Change connection team name part for every student of that vm

        # -------------------------------------------------------------
        # Remove access to deleted students
        # -------------------------------------------------------------
        for email in remove_emails:
            delete_user(db_session, guac, email, connection_id)

        # -------------------------------------------------------------
        # Create new student connection and access
        # -------------------------------------------------------------
        for email in add_emails:
            register_new_user(db_session, guac, email, connection_id)
            
    except HTTPError as http_err:
        status = http_err.response.status_code
        error_msg = http_err.response.text
        raise RuntimeError(f"Guacamole API Error ({status}): {error_msg}") from http_err
    except RequestException as req_err:
        raise RuntimeError(f"Impossible to connect to Guacamole server: {str(req_err)}") from req_err

# --------------------------------------------
# User management
# --------------------------------------------
    
def delete_user(db_session: Session, guac: Guacamole, email: str, connection_id: int):
    try:
        guac.connections.revoke_connection(
            username=email,
            connection_id=connection_id,
            permission="READ"
        )
        logging.info(f"Successfully revoked Guacamole access for {email} on connection {connection_id}.")

    except HTTPError as e:
        if getattr(e.response, 'status_code', None) == 404:
            logging.info(f"Guacamole resource already missing for {email} (404). Ignoring.")
        else:
            logging.error(f"Guacamole API HTTPError: {e.response.text if hasattr(e.response, 'text') else str(e)}")
            raise

def register_new_user(db_session: Session, guac: Guacamole, email: str, connection_id: int):
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
    logging.info(f"[GUACAMOLE] Assign connection for user '{email}' -> '{connection_id}'")
    try:
        guac.users.assign_connection(
            username=email,
            permission="READ",
            connection_id=str(connection_id),
        )
    except HTTPError as e:
        print(f"[GUACAMOLE] Failed to assign connection in Guacamole: {str(e)}")

# --------------------------------------------
# Connection
# --------------------------------------------
    
async def register_guacamole_access_single_user(db_session: Session, websocket: WebSocket, config_id: int):
    # Authenticate to Guacamole REST API via admin account
    guac = Guacamole(
        hostname=GUACAMOLE_URL,
        username=GUAC_ADMIN_USER,
        password=GUAC_ADMIN_PASS
    )

    await websocket.send_text("[VM] [REGISTER] [GUAC] Successfully connected to guacamole.")

    vm_data = db.get_vm_byid(db_session, config_id)
    if not vm_data:
        logging.error(f"[VM] [REGISTER] [GUAC] No VM Matched with the config id '{config_id}'")
        websocket.send_text(f"[VM] [REGISTER] [GUAC] No VM Matched with the config id '{config_id}'")
        return

    user_data = db.get_user(db_session, vm_data.name)
    if not user_data:
        logging.error(f"[VM] [REGISTER] [GUAC] No user Matched with the name '{vm_data.name}'")
        websocket.send_text(f"[VM] [REGISTER] [GUAC] No user Matched with the config id '{vm_data.name}'")
        return
        
    connection_name = f"{vm_data.name}"
    connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
    connection_payload.update({
        "name": connection_name,
        "parameters": {
            "username": user_data.username,
            "hostname": vm_data.ip,
            "password": user_data.password
        }
    })

    # Create guacamole connection
    try:
        connection = guac.connections.create(connection_payload)
        conn_id = connection["identifier"]
        db.update_connection_id_vm(db_session, config_id, conn_id)
        await websocket.send_text(f"[GUACAMOLE] Successfully created connection: '{vm_data.name}' (ID: {vm_data.guac_conn_id})")
        logging.info(f"[GUACAMOLE] Successfully created connection: '{vm_data.name}' (ID: {vm_data.guac_conn_id})")
    except TypeError as e:
        await websocket.send_text(f"[GUACAMOLE] Error: Connection already exists.")
        raise ValueError(f"Connection {vm_data.pve_id} already exists in guacamole. Please delete it.")

    for guac_user_mail in list(vm_data.guac_users):
        register_new_user(db_session, guac, guac_user_mail, vm_data.guac_conn_id)

    db.vm_update_status(db_session, vm_data.id, db.VMStatus.registered)
    await websocket.send_text(f"[GUACAMOLE] Successfully registered users.")    
    
async def register_guacamole_access_multiple_users(db_session: Session, websocket: WebSocket, config_id):
    # Authenticate to Guacamole REST API via admin account
    guac = Guacamole(
        hostname=GUACAMOLE_URL,
        username=GUAC_ADMIN_USER,
        password=GUAC_ADMIN_PASS
    )

    await websocket.send_text("[GUACAMOLE] Successfully connected to guacamole.")

    vm_data = db.get_vm_byid(db_session, config_id)
    if not vm_data:
        return

    for user in list(vm_data.users):

        user_data = db.get_user(db_session, user.mail)
        if not user_data:
            logging.error(f"No user matched with the mail {user.mail}")
            return
        
        connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
        connection_payload.update({
            "name": vm_data.name,
            "parameters": {
                "hostname": vm_data.ip,
                "username": user_data.username,
                "password": user_data.password
            }
        })
        
        # Create guacamole connection
        try:
            connection = guac.connections.create(connection_payload)
            conn_id = connection["identifier"]
            db.update_connection_id_vm(db_session, config_id, conn_id)
            await websocket.send_text(f"[GUACAMOLE] Successfully created connection: '{vm_data.name}' (ID: {vm_data.guac_conn_id})")
            logging.info(f"[GUACAMOLE] Successfully created connection: '{vm_data.name}' (ID: {vm_data.guac_conn_id})");
        except TypeError as e:
            await websocket.send_text(f"[GUACAMOLE] Error: Connection already exists.")
            raise ValueError(f"Connection {config_id} already exists in guacamole. Please delete it.")

        # Create guacamole user
        try:
            user_payload = deepcopy(USER_PAYLOAD_TEMPLATE)
            user_payload["username"] = user.mail
            guac.users.create(user_payload)
        except HTTPError as e:
            status_code = e.response.status_code
            if status_code == 400:
                await websocket.send_text(f"[GUACAMOLE] User {user.mail} already exists.")
            else:
                raise

        # Assign connection permission to the user
        try:
            guac.users.assign_connection(
                username=user.mail,
                permission="READ",
                connection_id=vm_data.guac_conn_id,
            )
            await websocket.send_text(f"[GUACAMOLE] Successfully granted student '{user.mail}:{user.username}' access to '{vm_data.name}'")
        except HTTPError as e:
            status_code = e.response.status_code
            if status_code == 500:
                await websocket.send_text(f"[GUACAMOLE] Connection already assigned for '{user.mail}'")
            else:
                raise
