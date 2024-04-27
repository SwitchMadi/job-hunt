import gspread
import pandas as pd
from gspread.exceptions import WorksheetNotFound
from googleapiclient.discovery import build

from utilities.logging import get_logger
from utilities.google_services import get_google_credentials
from utilities.google_services.drive import DriveResource


logger = get_logger(name="sheet", file_name="job-hunt")


class Sheet:
    def __init__(self, sheet_id=None, title=None, folder_id=None):
        credentials = get_google_credentials(scopes=["sheet"])
        self.gspread_client = gspread.authorize(credentials)
        self.google_api_client = build("sheets", "v4", credentials=credentials)

        if sheet_id:
            self.drive_resource = DriveResource(resource_id=sheet_id)
        else:
            self.drive_resource = DriveResource(
                name=title, resource_type="sheet", parent_folder_id=folder_id
            )

        self.sheet = self.gspread_client.open_by_url(self.sheet_url)

    def delete(self):
        del self.drive_resource

    @property
    def sheet_url(self):
        return f"https://docs.google.com/spreadsheets/d/{self.drive_resource.id}"

    @property
    def tabs(self):
        return self.sheet.worksheets()

    def share(self, email, role="writer"):
        return self.drive_resource.share(email=email, role=role)

    def get_tab(self, tab_name):
        try:
            return self.sheet.worksheet(tab_name)
        except WorksheetNotFound:
            logger.warn(
                f"Tab with name {tab_name} doesn't exit in sheet {self.drive_resource.id}."
            )
            return None

    def add_new_tab(self, tab_name, rows=1000, cols=26):
        logger.info(f"Adding tab {tab_name} to sheet {self.drive_resource.id}...")

        tab = self.get_tab(tab_name)
        if tab is None:
            tab = self.sheet.add_worksheet(title=tab_name, rows=rows, cols=cols)
            return tab
        else:
            logger.warn(
                f"Tab {tab_name} already exists in sheet {self.drive_resource.id}."
            )
            return None

    def delete_tab(self, tab_name):
        logger.info(f"Deleting tab {tab_name} from sheet {self.drive_resource.id}...")

        tab = self.get_tab(tab_name)
        if tab:
            self.sheet.del_worksheet(tab)
            return True
        else:
            logger.warn(
                f"Cannot delete tab {tab_name} as it doesn't exit in sheet {self.drive_resource.id}."
            )
            return False

    def read_tab(self, tab_name):
        tab = self.get_tab(tab_name)
        data = tab.get_all_records()
        return pd.DataFrame(data)

    def get_filled_row_count(self, tab_name):
        # Query to find the last non-empty row in the sheet
        range_name = f"'{tab_name}'!A1:Z"  # Assuming data doesn't go beyond column Z, adjust range as needed
        result = (
            self.google_api_client.spreadsheets()
            .values()
            .get(spreadsheetId=self.drive_resource.id, range=range_name)
            .execute()
        )
        values = result.get("values", [])

        if not values:
            return 0

        # Count non-empty rows
        filled_rows = sum([1 for row in values if any(cell != "" for cell in row)])
        return filled_rows

    def write_dataframe_to_tab(self, df, tab_name, mode="replace"):
        tab = self.get_tab(tab_name)
        if not tab:
            tab = self.add_new_tab(tab_name)

        row_count = self.get_filled_row_count(tab_name)
        if row_count == 0:
            mode = "replace"

        if mode == "replace":
            tab.clear()  # Clear the existing data

        if mode == "append":
            # Get the header from the sheet to align columns
            existing_headers = tab.row_values(1)
            new_columns = [col for col in df.columns if col not in existing_headers]
            if new_columns:
                # Append new columns to the end of existing headers
                existing_headers = existing_headers + new_columns
                tab.update(
                    "A1:" + chr(64 + len(existing_headers)) + "1", [existing_headers]
                )

            # Reorder and/or add new columns DataFrame to match the order in the sheet
            df = df.reindex(columns=existing_headers, fill_value="")

            data_to_upload = df.values.tolist()
            tab.append_rows(data_to_upload)
        else:
            data_to_upload = [df.columns.values.tolist()] + df.values.tolist()
            tab.update(
                data_to_upload, value_input_option="USER_ENTERED"
            )  # Update sheet with new data

        return True

    def reset_tab_row_heights(self, tab_name, height=21):
        tab = self.get_tab(tab_name)
        tab_id = tab.id
        row_count = self.get_filled_row_count(tab_name)

        requests = [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": tab_id,
                        "dimension": "ROWS",
                        "startIndex": 0,  # Update from the first row
                        "endIndex": row_count,  # Update up to the 1000th row, adjust as needed
                    },
                    "properties": {"pixelSize": height},  # Set the height
                    "fields": "pixelSize",
                }
            }
        ]

        body = {"requests": requests}
        response = (
            self.google_api_client.spreadsheets()
            .batchUpdate(spreadsheetId=self.drive_resource.id, body=body)
            .execute()
        )
        logger.info(f"Height reset script run. Response -\n{response}")

        return True
