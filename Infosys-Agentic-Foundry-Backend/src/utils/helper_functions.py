# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
from dotenv import load_dotenv
from datetime import datetime, timezone


load_dotenv()

def get_timestamp() -> datetime:
    """
    Returns the current UTC datetime as a naive datetime object.

    This strips the timezone info after retrieving the UTC time.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resolve_and_get_additional_no_proxys():
    no_proxy = os.environ.get("NO_PROXY", "")
    additional_no_proxys = os.getenv("ADDITIONAL_NO_PROXYS", "")
    if not additional_no_proxys:
        return no_proxy
    if not no_proxy:
        return additional_no_proxys
    no_proxy = no_proxy.split(",")
    additional_no_proxys = additional_no_proxys.split(",")
    combined_no_proxy = list(set(no_proxy + additional_no_proxys))
    return ",".join(combined_no_proxy)


