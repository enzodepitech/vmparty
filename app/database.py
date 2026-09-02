import logging
import os
from typing import Optional, Tuple, List

from app.core.security import create_user_password
from sqlalchemy import create_engine, select, Table, Column, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, relationship
from sqlalchemy.exc import IntegrityError

from app.core.utils import sanitize_email_to_username

# SQLAlchemy requires the sqlite:/// prefix
DB_DIR = "storage"
DB_PATH = f"sqlite:///{DB_DIR}/app.db"

# engine manages the connection pool
engine = create_engine(DB_PATH, echo=False)

class Base(DeclarativeBase):
    pass

# ---------------------------------------------------------
# Association Table for Many-to-Many
# ---------------------------------------------------------

user_vm_association = Table(
    "user_vm_association",
    Base.metadata,
    Column("user_id", ForeignKey("vm_users.id", ondelete="CASCADE"), primary_key=True),
    Column("vm_id", ForeignKey("vm_configs.id", ondelete="CASCADE"), primary_key=True),
)

# ---------------------------------------------------------
# Data Models
# ---------------------------------------------------------
class VMConfig(Base):
    __tablename__ = "vm_configs"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]
    pve_id: Mapped[int] = mapped_column(unique=True)
    ip: Mapped[str] = mapped_column(unique=True)
    has_shared_user: Mapped[bool]
    is_container: Mapped[bool]
    guac_conn_id: Mapped[int] = mapped_column(unique=True, default=0)

    # Replaces 'student_emails' string
    users: Mapped[List["VMUser"]] = relationship(
        secondary=user_vm_association, 
        back_populates="vms"
    )


class VMUser(Base):
    __tablename__ = "vm_users"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mail: Mapped[str] = mapped_column(unique=True)
    username: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]

    # Back-reference to see all VMs a user belongs to
    vms: Mapped[List["VMConfig"]] = relationship(
        secondary=user_vm_association, 
        back_populates="users"
    )    
    
# ---------------------------------------------------------
# Database Operations
# ---------------------------------------------------------
def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    # Creates all tables based on the models above if they don't exist
    Base.metadata.create_all(engine)

def get_db():
    with Session(engine) as session:
        yield session
    
def get_user(db_session: Session, mail: str) -> VMUser | None:
    return db_session.scalar(select(VMUser).where(VMUser.mail == mail))
    
def get_vm(db_session: Session, pve_id: int) -> VMConfig | None:
    return db_session.scalar(select(VMConfig).where(VMConfig.pve_id == pve_id))

def get_vm_byid(db_session: Session, config_id: int) -> VMConfig | None:
    return db_session.scalar(select(VMConfig).where(VMConfig.id == config_id))

def create_vm(db_session: Session, vm_config: VMConfig, student_emails: str):
    db_session.add(vm_config)

    unique_emails = set(student_emails.split(','))
    
    for email in unique_emails:
        # Check if user exists
        user = db_session.scalar(select(VMUser).where(VMUser.mail == email))

        # Create user if not exists
        if not user:
            username = sanitize_email_to_username(email)
            user = VMUser(mail=email, username=username, password=create_user_password())
            db_session.add(user)

        # Add user to the vm config
        vm_config.users.append(user)

    try:
        db_session.commit()
        logging.info(f"VM '{vm_config.name}' successfully created.")
    except IntegrityError:
        db_session.rollback()
        logging.error("VM ID must be unique.")
        raise ValueError("Cannot add VM: VM ID must be unique")
        
def update_connection_id_vm(db_session: Session, vm_id: int, conn_id: int):
    vm = db_session.scalar(select(VMConfig).where(VMConfig.vm_id == vm_id))
    if vm:
        vm.conn_id = conn_id
        db_session.commit()
        logging.info(f"Updated connection ID for VM '{vm_id}'.")
    else:
        logging.warning(f"No VM found with ID '{vm_id}' to update.")

def delete_vm(db_session: Session, config_id: int) -> bool:
    vm = db_session.get(VMConfig, config_id)
    if not vm:
        logging.warning(f"No VM found with id '{config_id}'")
        return False
        
    # Keep a reference to the users before deleting the VM
    affected_users = list(vm.users)
    
    # Deleting the VM automatically removes the links in the association table
    db_session.delete(vm)
    
    # Orphan cleanup: Delete users who no longer belong to ANY virtual machine
    for user in affected_users:
        # If the user's vms list is now empty, they have no active projects
        if not user.vms: 
            db_session.delete(user)
            logging.info(f"Deleted orphaned user {user.mail}")

    db_session.commit()
    logging.info(f"VM '{config_id}' deleted successfully.")
    return True
            
def delete_user(db_session: Session, mail: str) -> bool:
    user = db_session.scalar(select(VMUser).where(VMUser.mail == mail))
    
    if not user:
        logging.warning(f"Cannot delete: No user found with email '{mail}'.")
        return False
        
    # Optional: Check if deleting this user leaves any of their VMs completely empty
    affected_vms = list(user.vms)
    
    # Deleting the user automatically drops their links in user_vm_association
    db_session.delete(user)
    
    # Check for empty VMs (orphaned infrastructure)
    for vm in affected_vms:
        if len(vm.users) == 0:  # The user we just deleted was the last one
            logging.warning(f"VM '{vm.team_name}' (ID: {vm.vm_id}) now has 0 users.")
            # db.delete(vm) # Uncomment if you want to auto-destroy empty VMs

    db_session.commit()
    logging.info(f"User '{mail}' deleted successfully.")
    return True
