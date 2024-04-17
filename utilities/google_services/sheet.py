from utilities.google_services.drive import get_drive_client


def create_sheet(sheet_title, folder_id, drive_client=None):
    """Create a new Google Sheet in a specific folder."""
    if drive_client is None:
        drive_client = get_drive_client()

    file_metadata = {
        "name": sheet_title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [folder_id],
    }
    file = drive_client.files().create(body=file_metadata, fields="id").execute()
    return file.get("id")
