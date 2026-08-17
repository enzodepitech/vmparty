import unicodedata
import re

DEFAULT_USERNAME = "student"

# Source - https://stackoverflow.com/a/295466
# Posted by S.Lott, modified by community. See post 'Timeline' for change history
# Retrieved 2026-08-17, License - CC BY-SA 4.0
def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')

def sanitize_email_to_username(email: str) -> str:
    """
    Modify email to make it POSIX friendly
    """
    return email.split("@")[0].replace(".", "_")
