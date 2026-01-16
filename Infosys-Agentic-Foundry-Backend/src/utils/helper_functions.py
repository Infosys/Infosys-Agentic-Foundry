# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import ast
import json
from dotenv import load_dotenv
from datetime import datetime, timezone


load_dotenv()

def get_timestamp() -> datetime:
    """
    Returns the current UTC datetime as a naive datetime object.

    This strips the timezone info after retrieving the UTC time.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def convert_value_type_of_candidate_as_given_in_reference(reference: dict, candidate: dict) -> dict:
    """
    Convert the values of `candidate` dict to the types of the corresponding values in `reference` dict.
    Only keys present in both dicts are converted.

    Args:
        reference (dict): The dictionary with desired value types.
        candidate (dict): The dictionary whose values will be converted.

    Returns:
        dict: A new dictionary with converted value types.
    """
    def check_match_and_get(ref_value, cand_value):
        if type(ref_value) == type(cand_value):
            return cand_value
        raise TypeError("Type mismatch after eval")

    result = dict(candidate)
    for key, cand_value in candidate.items():
        if key in reference:
            ref_value = reference[key]
            try:
                updated_cand_value = json.loads(cand_value)
                result[key] = check_match_and_get(ref_value, updated_cand_value)
            except Exception:
                try:
                    updated_cand_value = ast.literal_eval(cand_value)
                    result[key] = check_match_and_get(ref_value, updated_cand_value)
                except Exception:
                    try:
                        result[key] = type(ref_value)(cand_value)
                    except Exception:
                        result[key] = cand_value  # fallback if conversion fails
    return result


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


def build_effective_query_with_user_updates(original_query: str, user_update_events: list, current_query: str = None) -> str:
    """
    Builds an effective query by appending user tool feedback updates to the original query.
    
    Args:
        original_query: The original query string
        user_update_events: List of user update events containing tool feedback
        current_query: Optional query to filter events by (defaults to original_query if not provided)
    
    Returns:
        Enhanced query string with user updates appended, or original query if no updates
    """
    # Handle None or empty original_query
    if not original_query:
        original_query = ""
    
    # If no user update events, return original query
    if not user_update_events:
        return original_query
    
    # Use original_query as filter if current_query not provided
    filter_query = current_query if current_query is not None else original_query
    
    # Extract updates for the current query only
    updates_lines = []
    for ev in user_update_events:
        # Skip events from different queries
        if ev.get("query") and ev.get("query") != filter_query:
            continue
        line = f"message : {ev.get('message','N/A')}\n"
        updates_lines.append(line)
    
    # Build effective query with updates if present
    if updates_lines:
        updates_block = "\n".join(updates_lines)
        return (
            f"original_user_query: {original_query}\n\n--- User Tool Feedback Updates ---\n"
            f"tool_update_feedback: {updates_block}\n--- End Updates ---"
            f"""\n 

- original_user_query: the user's initial question/instruction.
- tool_update_feedback: a free-form statement describing corrected parameters or revised intent.

Your job:
1) Infer the revised/expected query and parameters solely from tool_update_feedback.
2) Treat the revision as the single source of truth. Do NOT proceed with the original query if there is any conflict.
3) Execute using the revised intent/parameters and produce the answer accordingly.

Rules:
- If tool_update_feedback indicates parameter changes (e.g., "a=8 and b=9 were modified into a=8 and b=8"), infer the corrected query (e.g., "what is 8*8") and use the revised parameters.
- If tool_update_feedback states a direct correction (e.g., "expected question was 8*8", "corrected to 8*8"), answer that.
"""
        )
    else:
        return original_query


