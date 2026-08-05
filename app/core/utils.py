def sanitize_email_to_username(email: str) -> str:
    """
    Modify email to make it POSIX friendly
    """
    return email.split("@")[0].replace(".", "_")
