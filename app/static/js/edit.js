// static/js/edit.js

let initialFormData = null;

async function openEdit(configId) {
    try {
        const response = await fetch(`/edit/${configId}`);
        if (!response.ok) throw new Error(`Erreur HTTP: ${response.status}`);
        
        const html = await response.text();
        const container = document.getElementById("modal-container");
        
        if (!container) {
            console.error("Element #modal-container not found in index.html");
            return;
        }

        container.innerHTML = html;

        const modal = document.getElementById("editModal");
        if (!modal) {
            console.error("Element #modal-container not found in injected HTML.");
            return;
        }

        initModalEvents(modal, configId);

        modal.showModal();
        const editForm = document.getElementById("editForm");
        if (editForm) {
            initialFormData = getFormState(editForm);
            checkChanges();
        }

        if (typeof window.initMultipleStudentWrapper === "function") {
            window.initMultipleStudentWrapper();
        }

    } catch (error) {
        console.error("Error when opening edit:", error);
    }
}

function initModalEvents(modal, configId) {
    const cancelBtn = document.getElementById("cancelBtn");
    const editForm = document.getElementById("editForm");

    if (cancelBtn) {
        cancelBtn.addEventListener("click", () => closeModal(modal));
    }

    if (editForm) {
        editForm.addEventListener("input", checkChanges);
        editForm.addEventListener("change", checkChanges);
        editForm.addEventListener("submit", (e) => {
            e.preventDefault();
            if (modal && modal.open) {
                modal.close();
            }
        });
    }

    modal.addEventListener("click", (e) => {
        const dialogBounds = modal.getBoundingClientRect();
        if (
            e.clientX < dialogBounds.left ||
            e.clientX > dialogBounds.right ||
            e.clientY < dialogBounds.top ||
            e.clientY > dialogBounds.bottom
        ) {
            closeModal(modal);
        }
    });
}

/**
 * Extrait les emails de tous les inputs et les transforme en chaîne "a@b.com, c@d.com"
 */
function getCombinedEmails() {
    const emailInputs = document.querySelectorAll('.student-email-item');
    const emails = Array.from(emailInputs)
                        .map(input => input.value.trim())
                        .filter(email => email.length > 0);
    
    return emails.join(', ');
}

function addStudentInput(emailValue = "") {
    const container = document.getElementById("student-emails-list");
    const div = document.createElement("div");
    div.className = "flex items-center justify-between gap-2 mb-2 student-input-group";
    div.innerHTML = `
      <input type="email"
             name="student_email_input"
             class="form-control student-email-item"
             value="${emailValue}" required>
        <button type="button"
                onclick="removeStudentInput(this)"
                class="h-10 w-10 rounded-full bg-red-600 text-white px-3 py-1 rounded text-sm hover:bg-red-700">
          <i class="fa fa-trash white" aria-hidden="true"></i>
        </button>
    `;
    container.appendChild(div);
    
    div.querySelector("input").addEventListener("input", checkChanges);
    if (typeof checkChanges === "function") {
        checkChanges();
    }
}

function removeStudentInput(button) {
    const container = document.getElementById("student-emails-list");
    if (!container) return;
    
    if (container.children.length > 1) {
        button.parentElement.remove();
        checkChanges();
    } else {
        alert("You need at least one user email.");
    }
}

function getPayloadForSubmit() {
    const editForm = document.getElementById("editForm");
    const formData = new FormData(editForm);

    return {
        team_name: formData.get("team_name"),
        vm_id: parseInt(formData.get("vm_id")),
        student_emails: getCombinedEmails()
    };
}

function getFormState(form) {
    const editForm = form || document.getElementById("editForm");
    if (!editForm) return "";

    const formData = new FormData(editForm);
    formData.delete("student_email_input");
    formData.set("student_emails", getCombinedEmails());

    return new URLSearchParams(formData).toString();
}

function checkChanges() {
    const editForm = document.getElementById("editForm");
    const submitBtn = document.getElementById("submitBtn");
    
    if (!editForm || !submitBtn) return;

    const currentFormData = getFormState(editForm);
    const hasChanged = currentFormData !== initialFormData;
    
    submitBtn.disabled = !hasChanged;
}

function closeModal(modal) {
    const targetModal = modal || document.getElementById("editModal");
    const editForm = document.getElementById("editForm");
    const submitBtn = document.getElementById("submitBtn");

    if (targetModal) targetModal.close();
    if (editForm) editForm.reset();
    if (submitBtn) submitBtn.disabled = true;
}

window.openEdit = openEdit;
window.getCombinedEmails = getCombinedEmails;
