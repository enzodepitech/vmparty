import yaml
import os
from app.database import get_db_connection

def export_ansible_config():
    os.makedirs("storage/exports", exist_ok=True)
    conn = get_db_connection()
    configs = conn.execute("SELECT * FROM configs").fetchall()
    conn.close()

    vms_list = []
    for conf in configs:
        emails = conf["student_emails"].split(",")
        usernames = [e.strip().split("@")[0] for e in emails if e.strip()]
        
        vms_list.append({
            "vmid": conf["vm_id"],
            "name": conf["team_name"].lower().strip().replace(" ", "-"),
            "ip": conf["vm_ip"],
            "students": usernames
        })

    # Écriture du fichier de variables pour Ansible
    with open("storage/exports/vars.yml", "w") as f:
        yaml.dump({"vms": vms_list}, f)

    return len(vms_list)
