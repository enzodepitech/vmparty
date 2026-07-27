document.addEventListener("DOMContentLoaded", () => {
    const emailInput = document.getElementById("student-email-input");
    const tagsContainer = document.getElementById("email-tags-container");
    const hiddenInput = document.getElementById("students-hidden-input");
    const form = document.getElementById("vm-config-form");

    let studentEmails = [];

    function updateHiddenInput() {
        hiddenInput.value = studentEmails.join(",");
    }

    function createTag(email) {
        const tag = document.createElement("span");
        tag.className = "inline-flex items-center gap-1 bg-indigo-600/30 text-slate-900 border border-indigo-500/30 text-xs font-medium px-2 py-1 rounded-md";
        tag.innerHTML = `
            <span>${email}</span>
            <button type="button" class="focus:outline-none text-slate-900 font-bold ml-1">&times;</button>
        `;

        // Remove tag on button click without submitting form
        tag.querySelector("button").addEventListener("click", (e) => {
            e.preventDefault(); // Stop event propagation to form
            studentEmails = studentEmails.filter(item => item !== email);
            tag.remove();
            updateHiddenInput();
        });

        return tag;
    }

    // Keydown handler to prevent unwanted form submission on Enter / Backspace
    emailInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault(); // CRITICAL: Stop Enter key from submitting the form

            const email = emailInput.value.trim();
            // Basic email validation regex
            const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

            if (email && isValidEmail && !studentEmails.includes(email)) {
                studentEmails.push(email);
                tagsContainer.appendChild(createTag(email));
                updateHiddenInput();
                emailInput.value = ""; // Clear for next input
            }
        } else if (e.key === "Backspace" && emailInput.value === "" && studentEmails.length > 0) {
            e.preventDefault(); // Stop browser back-navigation
            const lastEmail = studentEmails.pop();
            tagsContainer.lastChild.remove();
            emailInput.value = lastEmail;
            updateHiddenInput();
        }
    });

    // Process submission only on explicit form submit
    form.addEventListener("submit", (e) => {
        // If user typed an email but didn't press Enter before clicking Submit
        const remainingEmail = emailInput.value.trim();
        const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(remainingEmail);

        if (remainingEmail && isValidEmail && !studentEmails.includes(remainingEmail)) {
            studentEmails.push(remainingEmail);
            updateHiddenInput();
        }

        console.log("Form submitting with students:", hiddenInput.value);
        // Form submits normally to FastAPI backend here
    });
});
