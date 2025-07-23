# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from datetime import datetime, timezone
def get_timestamp() -> datetime:
    """
    Returns the current UTC datetime as a naive datetime object.

    This strips the timezone info after retrieving the UTC time.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


