from app.core.security import create_user_password
from app.core.utils import slugify
from fastapi import FastAPI, Request, Form, HTTPException,  WebSocket, WebSocketDisconnect, Depends, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import logging
import asyncio

import app.services.guacamole as guacamole
import app.services.ansible as ansible
import app.database as db

from app.auth import ADMIN_USERNAME, ADMIN_PASSWORD_HASH, verify_password, create_session_token, require_admin, require_admin_ws

# ----------------------------------------------------
# Init application
# ----------------------------------------------------

app = FastAPI(title="VM Party")

db.init_db()

# Allow https traffic over proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Template file directory
templates = Jinja2Templates(directory="app/templates")

# ----------------------------------------------------
# UI Routes
# ----------------------------------------------------

@app.get("/")
async def read_dashboard(request: Request, admin_user: str = Depends(require_admin)):
    conn = db.get_db_connection()
    configs = conn.execute("SELECT * FROM configs ORDER BY id DESC").fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"configs": configs}
    )

# ----------------------------------------------------
# Action Routes (Add, Delete, Edit)
# ----------------------------------------------------

@app.websocket("/ws/add")
async def add_config(websocket: WebSocket,
                     admin_user: str = Depends(require_admin_ws)
                     ):
    await websocket.accept()

    try:
        await websocket.send_text(f"[ADD] Fetching data from front...")
        
        # Fetch data
        data = await websocket.receive_json()
        
        team_name = data.get("team_name")
        vm_id = data.get("vm_id")
        vm_ip = data.get("vm_ip")
        student_emails = data.get("student_emails")
        has_single_user = data.get("single_user")

        logging.info(f"Single User: {has_single_user}")

        # Create users in the database
        await websocket.send_text(f"[ADD] Starting registring students...")
        if has_single_user:
            db.create_user(slugify(team_name), create_user_password())
        else:
            for mail in student_emails.split(","):
                db.create_user(mail, create_user_password())

        # Create vm config in the database
        await websocket.send_text(f"[ADD] Starting registring VM '{vm_id}:{team_name}'...")
        db.create_vm(team_name, vm_id, vm_ip, student_emails, has_single_user)

        await websocket.send_text(f"[ADD] Successfully Created VM in DB.")

        # Run provider playbook
        await ansible.run_provide(websocket, vm_id)

        await websocket.send_text(f"[ADD] Successfully Provide VM.")

        # Run provisioner playbook
        await ansible.run_provision(websocket, vm_id, has_single_user)

        await websocket.send_text(f"[ADD] Successfully Provision VM.")

        # Register vm guacamole access
        if has_single_user:
            await guacamole.register_guacamole_access_single_user(websocket, vm_id)
        else:
            # await guacamole.register_one_guacamole_access(websocket, vm_id)
            pass

        await websocket.send_text(f"[ADD] Successfully Register VM to Guacamole.")
    except WebSocketDisconnect:
        logging.info("Client disconnected during deployment execution.")
    except ValueError as ve:
        await websocket.send_text(f"[ADD] Error when registring the vm: {str(ve)}")
        logging.error(f"[ADD] Error when registring the vm: {str(ve)}")
    except TypeError as te:
        await websocket.send_text(f"[ADD] Type Error: {str(te)}")
        logging.error(f"[ADD] Type Error: {str(te)}")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            # Socket already closed
            pass        

@app.get("/edit/{config_id}", response_class=HTMLResponse)
async def get_edit_page(request: Request, config_id: int, admin_user: str = Depends(require_admin)):
    conn = db.get_db_connection()
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

    await websocket.send_text(f"[EDIT] Editing config {config_id}...")

    try:
        await websocket.send_text("[EDIT] Fetching data...")
        data = await websocket.receive_json()
        
        team_name = data.get("team_name")
        vm_id = data.get("vm_id")
        vm_ip = data.get("vm_ip")
        student_emails = data.get("student_emails")

        await websocket.send_text("[EDIT] Fetching old VM configuration...")
        conn = db.get_db_connection()
        old_config = conn.execute("SELECT * FROM configs WHERE id = ?", (config_id,)).fetchone()
    
        if not old_config:
            conn.close()
            await websocket.send_text("[EDIT] Error: no configuration matched found...")
            raise HTTPException(status_code=404, detail="No configuration matched")

        await websocket.send_text("[EDIT] Processing students to add and remove configuration...")
        old_list = set(filter(None, [s.strip() for s in old_config["student_emails"].split(",")]))
        new_list = set(filter(None, [s.strip() for s in student_emails.split(",")]))
        
        to_add = list(new_list - old_list) # Students to add
        to_remove = list(old_list - new_list) # Students to remove

        # Register new students and delete olds
        await websocket.send_text("[EDIT] Creating students to add in DataBase...")
        for mail in to_add:
            db.create_user(mail, create_user_password())

        await websocket.send_text("[EDIT] Deleting students to remove from DataBase...")
        for mail in to_remove:
            # db.delete_user(mail)
            pass

        try: 
            # Edit server VM name & Update Linux users
            await websocket.send_text("[EDIT] Ansible updating VM on server...")
            ansible_success = await ansible.run_edit(
                websocket,
                vmid=vm_id,
                new_team_name=team_name,
                students_to_add=to_add,
                students_to_remove=to_remove
            )

            if ansible_success:
                # Update guacamole access
                await websocket.send_text("[EDIT] Updating Guacamole Resources...")
                await guacamole.update_guacamole_resources(
                    websocket,
                    old_team_name=old_config["team_name"],
                    add_emails=to_add,
                    remove_emails=to_remove
                )

                await websocket.send_text("[EDIT] Updating DataBase...")
                # Update DB
                conn.execute(
                    """UPDATE configs 
                    SET team_name = ?, vm_id = ?, vm_ip = ?, student_emails = ? 
                    WHERE id = ?""",
                    (team_name, vm_id, vm_ip, student_emails, config_id)
                )
                conn.commit()

                await websocket.send_text("[EDIT] Successfully edit configuration!")
            else:
                await websocket.send_text("[EDIT] Error: Ansible edit process did not ended successfully.")
        except Exception as e:
            conn.rollback()
            await websocket.send_text(f"[EDIT] Edition error: {str(e)}")
        finally:
            conn.close()
            
    except WebSocketDisconnect:
        logging.info("[EDIT] Client disconnected during deployment execution.")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            # Socket already closed
            pass

@app.websocket("/ws/delete/{config_id}")
async def delete_config(config_id: int,
                        websocket: WebSocket,
                        admin_user: str = Depends(require_admin_ws)):
    await websocket.accept()

    await websocket.send_text(f"[DELETE] Delete config {config_id}...")

    try:
        # Delete in Proxmox
        await ansible.run_delete(websocket, config_id)

        # Delete it in the database only if delete on server worked
        db.delete_vm(config_id)
    except WebSocketDisconnect:
        logging.info("Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"[DELETE] Error when delete config {config_id}: {e}")
        logging.info(f"[DELETE] Error when delete config {config_id}: {e}")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            # Socket already closed
            pass

# ----------------------------------------------------
# Login
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
