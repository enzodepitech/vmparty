import yaml
import os
from app.database import get_db_connection
from app.services.guacamole import sanitize_email_to_username

def export_ansible_config():
    os.makedirs("storage/exports", exist_ok=True)
    conn = get_db_connection()
    configs = conn.execute("SELECT * FROM configs").fetchall()
    conn.close()

    vms_list = []
    for conf in configs:
        emails = conf["student_emails"].split(",")
        
        vms_list.append({
            "vmid": conf["vm_id"],
            "name": conf["team_name"],
            "ip": conf["vm_ip"],
            "students": emails
        })

    # Écriture du fichier de variables pour Ansible
    with open("storage/exports/vms_conf.yml", "w") as f:
        yaml.dump({"vms": vms_list}, f)

    return len(vms_list)
