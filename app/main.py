from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
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
    print(f"Successful export: {nb_vm} VMs created.")
    return RedirectResponse(url="/", status_code=303)
