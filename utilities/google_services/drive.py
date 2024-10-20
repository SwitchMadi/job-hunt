from googleapiclient.discovery import build

from utilities.logging import get_logger
from utilities.google_services import get_google_credentials

logger = get_logger(name="drive")


class DriveResource:
    def __init__(
        self, resource_id=None, name=None, resource_type=None, parent_folder_id=None
    ):
        credentials = get_google_credentials(["drive"])
        self.client = build("drive", "v3", credentials=credentials)

        if resource_id:
            metadata = self.client.files().get(fileId=resource_id, fields="*").execute()
        else:
            if resource_type == "folder":
                mime_type = "application/vnd.google-apps.folder"
            elif resource_type == "sheet":
                mime_type = "application/vnd.google-apps.spreadsheet"
            else:
                raise Exception(f"Unsupported resource type - {resource_type}")

            metadata = {
                "name": name,
                "mimeType": mime_type,
            }
            if parent_folder_id:
                metadata["parents"] = [
                    parent_folder_id
                ]  # Assign parent folder if provided

            metadata = self.client.files().create(body=metadata, fields="*").execute()

        for key, value in metadata.items():
            setattr(self, key, value)

        self.folder_resources = None

    def delete(self):
        self.client.files().delete(fileId=self.id).execute()
        logger.info(f"Drive resource {self.name} deleted successfully.")

    def share(self, email, role="writer"):
        """Share a file or folder with a given email address."""
        user_permission = {"type": "user", "role": role, "emailAddress": email}
        self.client.permissions().create(
            fileId=self.id,
            body=user_permission,
            fields="id",
        ).execute()
        logger.info(
            f"Drive resource {self.name} successfully shared with {email} with role as {role}."
        )

    def get_folder_resources(self):
        if self.mimeType != "application/vnd.google-apps.folder":
            logger.warn(f"Cannot list resources of resource type {self.mimeType}.")
            return

        query = f"'{self.id}' in parents and trashed=false"
        results = (
            self.client.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
            )
            .execute()
        )
        items = results.get("files", [])
        self.folder_resources = items

        if not items:
            logger.info("No files found.")
            return []

        return items
