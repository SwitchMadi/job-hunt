from googleapiclient.discovery import build

from utilities.logging import get_logger
from utilities.google_services import get_google_credentials

logger = get_logger(name="drive", file_name="job-hunt")


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


def list_folder_resources(folder_id="root", client=None):
    """List all resources in a specified Google Drive folder or in the root."""
    if client is None:
        client = get_drive_client()

    query = f"'{folder_id}' in parents and trashed=false"
    results = (
        client.files()
        .list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000,
        )
        .execute()
    )
    items = results.get("files", [])
    if not items:
        logger.info("No files found.")
        return

    return items
