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

from app.services.guacamole import register_guacamole_access
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

@app.post("/edit/{config_id}")
async def edit_config(
    config_id: int,
    team_name: str = Form(...),
    vm_id: int = Form(...),
    vm_ip: str = Form(...),
    student_emails: str = Form(...),
    admin_user: str = Depends(require_admin)
):
    conn = get_db_connection()
    conn.execute(
        """UPDATE configs 
           SET team_name = ?, vm_id = ?, vm_ip = ?, student_emails = ? 
           WHERE id = ?""",
        (team_name, vm_id, vm_ip, student_emails, config_id)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{config_id}")
async def delete_config(config_id: int, admin_user: str = Depends(require_admin)):
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

            # Users registration (via guacamole rest api)
            try:
                await register_guacamole_access(websocket, "storage/exports/vms_conf.yml")
            except Exception as e:
                await websocket.send_text(f"--- Error configuring Guacamole access: {str(e)}")

            # Provide credentials via Ansible
            try:
                await provide_student_credentials(websocket)
                await websocket.send_text("--- Credentials successfully configured for all students! ---")
            except Exception as e:
                await websocket.send_text(f"--- Error configuring credentials access: {str(e)}")
                pass
                
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
