import asyncio
import os
import yaml
import logging
from guacapy import Guacamole
from guacapy.managers import ConnectionManager
from copy import deepcopy

GUACAMOLE_URL = os.getenv("GUACAMOLE_URL", "")
GUAC_ADMIN_USER = os.getenv("GUACAMOLE_API_USER", "")
GUAC_ADMIN_PASS = os.getenv("GUACAMOLE_API_PASSWORD", "")
DATABASE_SOURCE = "postgresql"

def _sync_register_guacamole_access(vars_file_path: str):
    """Synchronous execution block using guacapy."""
    # Parse Ansible vars file
    with open(vars_file_path, "r") as f:
        data = yaml.safe_load(f)
        vms = data.get("vms", [])

    if not vms:
        logging.error("No VMs found in vars file to register with Guacamole.")
        return

    # Authenticate to Guacamole REST API via admin account
    guac = Guacamole(
        hostname=GUACAMOLE_URL,
        username=GUAC_ADMIN_USER,
        password=GUAC_ADMIN_PASS,
    )

    logging.info("Successfully connected to guacamole.")

    # Process each deployed VM/LXC container
    for vm in vms:
        vm_name = vm["name"]
        vm_ip = vm["ip"]
        students = vm.get("students", [])

        connection_payload = deepcopy(ConnectionManager.SSH_TEMPLATE)
        connection_payload.update({
            "name": vm_name,
            "parameters": {
                "hostname": vm_ip
            }
        })

        # Create SSH Connection
        try :
            connection = guac.connections.create(connection_payload)
            conn_id = connection["identifier"]
            logging.info(f"Created Guacamole SSH Connection: '{vm_name}' (ID: {conn_id})")
        except Exception as _:
            # Connection already existing, updating connection
            connection = guac.connections.get_by_name(vm_name)
            conn_id = connection["identifier"]
            logging.info(f"Guacamole SSH Connection already exists: '{vm_name}' (ID: {conn_id})")

        # Assign access to students
        for student in students:

            student_mail = student + "@epitech.eu"
            try:
                guac.users.create({"username": student_mail })
            except Exception:
                # User already exists
                logging.info(f"User {student_mail} already exists in guacamole database.")
                pass

            # Assign connection permission to the user
            guac.users.assign_connection(
                username=student_mail,
                permission="READ",
                connection_id=conn_id,
            )
            logging.info(f"Granted student '{student}' access to '{vm_name}'")


async def register_guacamole_access(vars_file_path: str):
    """Async wrapper to run synchronous guacapy calls inside FastAPI's event loop."""
    await asyncio.to_thread(_sync_register_guacamole_access, vars_file_path)
