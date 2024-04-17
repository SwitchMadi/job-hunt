from googleapiclient.discovery import build

from utilities.google_services import get_google_credentials


def get_drive_client():
    credentials = get_google_credentials(["drive"])
    client = build("drive", "v3", credentials=credentials)
    return client


def create_drive_folder(folder_name, parent_id=None, client=None):
    """Create a folder in Google Drive, optionally within a specified parent folder."""
    if client is None:
        client = get_drive_client()

    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        file_metadata["parents"] = [parent_id]  # Assign parent folder if provided

    file = client.files().create(body=file_metadata, fields="id").execute()
    return file.get("id")


def delete_resource(resource_id, client=None):
    """Delete a file or folder in Google Drive by its ID."""
    if client is None:
        client = get_drive_client()

    client.files().delete(fileId=resource_id).execute()
    return True


def share_resource(resource_id, email, client=None):
    """Share a file or folder with a given email address."""
    if client is None:
        client = get_drive_client()

    user_permission = {"type": "user", "role": "writer", "emailAddress": email}
    client.permissions().create(
        fileId=resource_id,
        body=user_permission,
        fields="id",
    ).execute()

    return True
