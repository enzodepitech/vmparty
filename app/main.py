from fastapi import FastAPI, Request, Form, HTTPException,  WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import sqlite3
import logging
import asyncio
import os

from app.database import init_db, get_db_connection
from app.services.exporter import export_ansible_config

app = FastAPI(title="VM Party")

init_db()

templates = Jinja2Templates(directory="app/templates")

# --- UI ROUTE ---
@app.get("/")
async def read_dashboard(request: Request):
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
    student_emails: str = Form(...)
):
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
        conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/edit/{config_id}")
async def edit_config(
    config_id: int,
    team_name: str = Form(...),
    vm_id: int = Form(...),
    vm_ip: str = Form(...),
    student_emails: str = Form(...)
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
async def delete_config(config_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM configs WHERE id = ?", (config_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/export")
async def trigger_export():
    nb_vm = export_ansible_config()
    logging.info(f"Successful export: {nb_vm} VMs created.")
    return RedirectResponse(url="/", status_code=303)

@app.websocket("/ws/deploy")
async def deploy_websocket(websocket: WebSocket):
    await websocket.accept()

    playbook_cmd = [
        "ansible-playbook",
        "ansible/deploy_vms.yml",
        "-e",
        "@storage/exports/vars.yml"
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    print(env)

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
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode().rstrip())

        await process.wait()

        if process.returncode == 0:
            await websocket.send_text("--- Deployment Finished Successfully ---")
        else:
            await websocket.send_text(f"--- Deployment Failed (Exit Code {process.returncode}) ---")

    except WebSocketDisconnect:
        print("Client disconnected during deployment execution.")
    except Exception as e:
        await websocket.send_text(f"Error executing playbook: {str(e)}")
    finally:
        await websocket.close()
