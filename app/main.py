from app.services.provisionner import provide_student_credentials
from fastapi import FastAPI, Request, Form, HTTPException,  WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import sqlite3
import logging
import asyncio
import os

from app.services.guacamole import register_guacamole_access, update_guacamole_resources
from app.services.edit import run_ansible_edit

from app.database import init_db, get_db_connection
from app.services.exporter import export_ansible_config
from app.auth import ADMIN_USERNAME, ADMIN_PASSWORD_HASH, verify_password, create_session_token, require_admin, require_admin_ws


# --- Init app

VMS_CONF_FILE = "./vms_conf.yml"
EXPORT_PATH = "@storage/exports/"

app = FastAPI(title="VM Party")

init_db()

# Allow https traffic over proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Template file directory
templates = Jinja2Templates(directory="app/templates")

# --- UI ROUTE ---
@app.get("/")
async def read_dashboard(request: Request, admin_user: str = Depends(require_admin)):
    conn = get_db_connection()
    configs = conn.execute("SELECT * FROM configs ORDER BY id DESC").fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"configs": configs}
    )

# --- ACTION ROUTES ---
@app.post("/add")
async def add_config(
    team_name: str = Form(...),
    vm_id: int = Form(...),
    vm_ip: str = Form(...),
    student_emails: str = Form(...),
    admin_user: str = Depends(require_admin)
):
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO configs (team_name, vm_id, vm_ip, student_emails) VALUES (?, ?, ?, ?)",
            (team_name, vm_id, vm_ip, student_emails)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="VM ID must be unique.")
    finally:
        if conn:
            conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/edit/{config_id}", response_class=HTMLResponse)
async def get_edit_page(request: Request, config_id: int, admin_user: str = Depends(require_admin)):
    conn = get_db_connection()
    config = conn.execute("SELECT * FROM configs WHERE id = ?", (config_id,)).fetchone()
    conn.close()

    student_mails_list = config["student_emails"].split(",")

    return templates.TemplateResponse(
        request=request,
        name="edit.html",
        context={"config": config, "students": student_mails_list}
    )

@app.websocket("/ws/edit/{config_id}")
async def edit_config(config_id: int,
                      websocket: WebSocket,
                      admin_user: str = Depends(require_admin_ws),
                      ):
    await websocket.accept()

    await websocket.send_text(f"Editing config {config_id}...")

    try:
        data = await websocket.receive_json()
        
        team_name = data.get("team_name")
        vm_id = data.get("vm_id")
        vm_ip = data.get("vm_ip")
        student_emails = data.get("student_emails")
    
        conn = get_db_connection()
        old_config = conn.execute("SELECT * FROM configs WHERE id = ?", (config_id,)).fetchone()
    
        if not old_config:
            conn.close()
            raise HTTPException(status_code=404, detail="Config introuvable")

        old_list = set(filter(None, [s.strip() for s in old_config["student_emails"].split(",")]))
        new_list = set(filter(None, [s.strip() for s in student_emails.split(",")]))
        
        to_add = list(new_list - old_list) # Students to add
        to_remove = list(old_list - new_list) # Students to remove


        try: 
            # Edit server VM name & Update Linux users
            ansible_success = await run_ansible_edit(
                websocket,
                vmid=vm_id,
                new_team_name=team_name,
                students_to_add=to_add,
                students_to_remove=to_remove
            )

            if ansible_success == 0:
                # Update guacamole access
                await asyncio.to_thread(
                    update_guacamole_resources,
                    websocket,
                    connection_id=str(old_config["guac_connection_id"]),
                    new_team_name=team_name,
                    add_emails=to_add,
                    remove_emails=to_remove
                )

                # Update DB
                conn.execute(
                    """UPDATE configs 
                    SET team_name = ?, vm_id = ?, vm_ip = ?, student_emails = ? 
                    WHERE id = ?""",
                    (team_name, vm_id, vm_ip, student_emails, config_id)
                )
                conn.commit()
            else:
                await websocket.send_text("Ansible edit process did not ended successfully.")
        except Exception as e:
            conn.rollback()
            await websocket.send_text(f"Edition error: {str(e)}")
        finally:
            conn.close()
            
    except WebSocketDisconnect:
        logging.info("Client disconnected during deployment execution.")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            # Socket already closed
            pass

@app.post("/delete/{config_id}")
async def delete_config(config_id: int, admin_user: str = Depends(require_admin)):
    # Delete it in proxmox

    # Delete it in the database only if delete on server worked
    conn = get_db_connection()
    conn.execute("DELETE FROM configs WHERE id = ?", (config_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.websocket("/ws/deploy")
async def deploy_websocket(websocket: WebSocket, admin_user: str = Depends(require_admin_ws)):
    """
    Export configuration -> Deploy Vms -> Create users (Guacamole).
    """
    await websocket.accept()

    await websocket.send_text("--- Starting Configuration Export ---")

    # Export Configuration
    try :
        nb_vm = export_ansible_config()
    except Exception as e:
        logging.error(f"Error when exporting configuration file: {e}")
        await websocket.send_text(f"--- Error when exportings VM(s): {e} ---")
        return

    logging.info(f"Successful export: {nb_vm} VMs created.")
    await websocket.send_text(f"--- Successful exported {nb_vm} VM(s). ---")

    # Deploy VMs via Ansible
    playbook_cmd = [
        "ansible-playbook",
        "ansible/01_deploy.yml",
        "-e",
        "@storage/exports/vms_conf.yml"
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = await asyncio.create_subprocess_exec(
            *playbook_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )

        await websocket.send_text("--- Starting Ansible Deployment ---")

        # Stream logs line-by-line in real time
        while True:
            if process.stdout:
                line = await process.stdout.readline()
                if not line:
                    break
                await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text("--- Ansible Deployment Finished Successfully ---")
            await websocket.send_text("--- Starting Registering Guacamole connections... ---")

            try:
                await register_guacamole_access(websocket, "storage/exports/vms_conf.yml")
                await provide_student_credentials(websocket)
            except Exception as e:
                await websocket.send_text(f"--- Error: {str(e)}")
                
        else:
            await websocket.send_text(f"--- Deployment Failed (Exit Code {process.returncode}) ---")

    except WebSocketDisconnect:
        logging.info("Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"Error executing playbook: {str(e)}")
    finally:
        await websocket.close()


# ----------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
    )

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    # Verify username & Argon2 password hash
    if (ADMIN_PASSWORD_HASH is not None) and \
       (username == ADMIN_USERNAME) and \
       verify_password(password, ADMIN_PASSWORD_HASH):
        
        token = create_session_token(username)
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
        # Set HTTP-Only, Secure Cookie
        response.set_cookie(
            key="admin_session",
            value=token,
            httponly=True,  # Prevents JavaScript XSS access
            secure=True,    # Set to True in production (requires HTTPS)
            samesite="lax", # Mitigates CSRF attacks
            max_age=86400   # 24 hours
        )
        return response

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid username or password"},
        status_code=status.HTTP_401_UNAUTHORIZED
    )

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("admin_session")
    return response
