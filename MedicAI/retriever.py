import os
from pathlib import Path

def retrieve_files(person_name):
    """
    Retrieve all files (attachments) for a person from emails and WhatsApp.
    
    Returns: list of full file paths
    """
    files = []
    
    # Email attachments
    email_path = Path(f"emails/{person_name}/attachments")
    if email_path.exists():
        for file in email_path.iterdir():
            if file.is_file():
                files.append(str(file))
    
    # WhatsApp media
    whatsapp_path = Path(f"whatsapp/{person_name}")
    if whatsapp_path.exists():
        for file in whatsapp_path.iterdir():
            if file.is_file():
                files.append(str(file))
    
    return files