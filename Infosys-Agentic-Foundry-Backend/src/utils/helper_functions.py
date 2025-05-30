# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import datetime
def get_timestamp() -> str:
    """
    Returns the current timestamp in a formatted string.

    Returns:
        str: The formatted timestamp.
    """
    current_time = datetime.datetime.now()
    formatted_timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
    return formatted_timestamp

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

