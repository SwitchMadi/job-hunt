import gspread
import pandas as pd
from gspread.exceptions import WorksheetNotFound
from googleapiclient.discovery import build

from utilities.logging import get_logger
from utilities.google_services import get_google_credentials
from utilities.google_services.drive import get_drive_client


logger = get_logger(name="sheet", file_name="job-hunt")


def get_sheet_client(library="gspread"):
    credentials = get_google_credentials(scopes=["sheet"])

    if library == "gspread":
        client = gspread.authorize(credentials)
    elif library == "googleapiclient":
        client = build("sheets", "v4", credentials=credentials)
    else:
        logger.warn(f"'{library}' input for library param is incorrect.")
        return None

    return client


def create_sheet(sheet_title, folder_id, drive_client=None):
    """Create a new Google Sheet in a specific folder."""
    logger.info(f"Creating sheet {sheet_title} in folder {folder_id}...")
    if drive_client is None:
        drive_client = get_drive_client()

    file_metadata = {
        "name": sheet_title,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [folder_id],
    }
    file = drive_client.files().create(body=file_metadata, fields="id").execute()
    return file.get("id")


def add_new_tab_to_sheet(sheet_id, tab_name, rows=1000, cols=26, client=None):
    """Add a new tab (worksheet) to a Google Sheet."""
    logger.info(f"Adding tab {tab_name} to sheet {sheet_id}...")
    if client is None:
        client = get_sheet_client()

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    sheet = client.open_by_url(sheet_url)

    current_tabs = [tab.title for tab in sheet.worksheets()]
    if tab_name not in current_tabs:
        worksheet = sheet.add_worksheet(title=tab_name, rows=rows, cols=cols)
        return worksheet
    else:
        logger.warn(f"Tab {tab_name} already exists in sheet {sheet_id}.")
        return False


def delete_tab_from_sheet(sheet_id, tab_name, client=None):
    """Delete a tab (worksheet) from a Google Sheet."""
    logger.info(f"Deleting tab {tab_name} from sheet {sheet_id}...")
    if client is None:
        client = get_sheet_client()

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    sheet = client.open_by_url(sheet_url)

    current_tabs = [tab.title for tab in sheet.worksheets()]
    if tab_name in current_tabs:
        worksheet = sheet.worksheet(tab_name)
        sheet.del_worksheet(worksheet)
        return True
    else:
        logger.warn(
            f"Cannot delete tab {tab_name} as it doesn't exit in sheet {sheet_id}."
        )
        return False


def read_sheet(sheet_id, tab_name, client=None):
    """Read data from a Google Sheet into a pandas DataFrame using the tab name."""
    if client is None:
        client = get_sheet_client()

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet(tab_name)  # Get the worksheet by name
    data = worksheet.get_all_records()
    return pd.DataFrame(data)


def get_filled_row_count(sheet_id, tab_name, client=None):
    """Get the count of filled rows in a specified tab in a Google Sheet."""
    if client is None:
        client = get_sheet_client("googleapiclient")

    # Query to find the last non-empty row in the sheet
    range_name = f"'{tab_name}'!A1:Z"  # Assuming data doesn't go beyond column Z, adjust range as needed
    result = (
        client.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=range_name)
        .execute()
    )
    values = result.get("values", [])

    if not values:
        return 0

    # Count non-empty rows
    filled_rows = sum([1 for row in values if any(cell != "" for cell in row)])
    return filled_rows


def write_dataframe_to_sheet(df, sheet_id, tab_name, mode="replace", client=None):
    """Write a DataFrame to a specified Google Sheet tab. Modes: 'append', 'replace'"""
    if client is None:
        client = get_sheet_client()

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    sheet = client.open_by_url(sheet_url)
    try:
        worksheet = sheet.worksheet(tab_name)
        row_count = get_filled_row_count(sheet_id, tab_name)
        if row_count == 0:
            mode = "replace"

        if mode == "replace":
            worksheet.clear()  # Clear the existing data

        # Convert DataFrame to list of lists and update or append
        data_to_upload = [df.columns.values.tolist()] + df.values.tolist()
        if mode == "append":
            worksheet.append_rows(data_to_upload[1:])  # Append data, ignoring headers
        else:
            worksheet.update(
                data_to_upload, value_input_option="USER_ENTERED"
            )  # Update sheet with new data
    except WorksheetNotFound as e:
        logger.warn(f"{tab_name} not found in sheet {sheet_id}. {e}")
        add_new_tab_to_sheet(sheet_id, tab_name, client=client)
        write_dataframe_to_sheet(df, sheet_id, tab_name, mode=mode, client=client)

    return True


def get_tab_id_by_name(sheet_id, tab_name, client=None):
    """Retrieve a sheet ID based on the tab name from a Google Sheets document."""
    if client is None:
        client = get_sheet_client("googleapiclient")

    # Get metadata about all sheets in the spreadsheet
    sheet_metadata = client.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheets = sheet_metadata.get("sheets", "")

    # Search for the sheet (tab) by name
    for sheet in sheets:
        if sheet["properties"]["title"] == tab_name:
            return sheet["properties"]["sheetId"]
    return None  # Return None if no tab with that name exists


def reset_row_heights(sheet_id, tab_name, height=21, client=None):
    if client is None:
        client = get_sheet_client("googleapiclient")

    tab_id = get_tab_id_by_name(sheet_id=sheet_id, tab_name=tab_name, client=client)
    row_count = get_filled_row_count(sheet_id, tab_name)

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
        client.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
    )
    logger.info(f"Height reset script run. Response -\n{response}")

    return True
