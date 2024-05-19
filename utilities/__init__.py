import hashlib
import datetime
import shutil
import os


def generate_hash(string):
    hash_object = hashlib.sha256(string.encode())
    _hash = hash_object.hexdigest()

    return _hash


def time_ago_to_epoch(time_ago):
    # Get the current datetime
    now = datetime.datetime.now()

    # Split the input string to extract numbers and time units
    parts = time_ago.split()

    # Check if the format is correct (e.g., "2 hours ago")
    if len(parts) == 3 and parts[2] == "ago":
        try:
            value = int(parts[0])  # the 'X' in 'X hours ago'
            unit = parts[1]  # the 'hours' in 'X hours ago'

            # Calculate the time delta based on the unit
            if unit.startswith("second"):
                delta = datetime.timedelta(seconds=value)
            elif unit.startswith("minute"):
                delta = datetime.timedelta(minutes=value)
            elif unit.startswith("hour"):
                delta = datetime.timedelta(hours=value)
            elif unit.startswith("day"):
                delta = datetime.timedelta(days=value)
            elif unit.startswith("week"):
                delta = datetime.timedelta(weeks=value)
            elif unit.startswith("month"):
                delta = datetime.timedelta(days=value * 30)
            elif unit.startswith("year"):
                delta = datetime.timedelta(days=value * 365)
            else:
                return None  # Unsupported time unit

            # Calculate the past time
            past_time = now - delta

            # Return as Unix epoch time
            return int(past_time.timestamp())
        except ValueError:
            # In case of conversion errors
            return None
    else:
        return None


def zip_directory(source_dir, zip_file_path):
    """
    Zips the contents of the source directory and creates a zip file at the specified path.

    :param source_dir: Directory to be zipped.
    :param zip_file_path: Path where the zip file should be created.
    """
    shutil.make_archive(
        base_name=os.path.splitext(zip_file_path)[0], format="zip", root_dir=source_dir
    )


def unzip_directory(zip_file_path, extract_dir):
    """
    Unzips the contents of the zip file into the specified directory.

    :param zip_file_path: Path to the zip file.
    :param extract_dir: Directory where the contents should be extracted.
    """
    shutil.unpack_archive(zip_file_path, extract_dir)
