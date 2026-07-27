import asyncio
import os
import yaml
import logging
from guacapy import Guacamole

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

    # Process each deployed VM/LXC container
    for vm in vms:
        vm_name = vm["name"]
        vm_ip = vm["ip"]
        students = vm.get("students", [])

        # Create SSH Connection in Guacamole
        connection = guac.create_connection(
            name=vm_name,
            protocol="ssh",
            parameters={
                "hostname": vm_ip,
                "port": "22",
                # Optional connection settings:
                # "font-size": "14",
                # "color-scheme": "green-black"
            },
        )
        conn_id = connection["identifier"]
        logging.info(f"Created Guacamole SSH Connection: '{vm_name}' (ID: {conn_id})")

        # Assign access to every student mapped to this VM
        for student in students:
            # Ensure student user exists in PostgreSQL (OIDC matches exact username)
            try:
                guac.create_user(username=student)
            except Exception:
                # User already exists in database; proceed
                pass

            # Grant READ permission on the connection to the OIDC user
            guac.add_user_permission(
                username=student,
                permission_type="READ",
                connection_id=conn_id,
            )
            logging.info(f"Granted student '{student}' access to '{vm_name}'")


async def register_guacamole_access(vars_file_path: str):
    """Async wrapper to run synchronous guacapy calls inside FastAPI's event loop."""
    await asyncio.to_thread(_sync_register_guacamole_access, vars_file_path)
