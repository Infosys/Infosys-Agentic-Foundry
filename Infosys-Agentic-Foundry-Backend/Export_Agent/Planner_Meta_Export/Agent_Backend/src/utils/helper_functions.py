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


