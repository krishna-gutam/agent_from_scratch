import datetime
import json

from .decorator import tool


@tool("Get the current local date and time.")
def get_current_time() -> str:
    current_time = datetime.datetime.now().astimezone()
    return json.dumps({"current_time": current_time.isoformat(timespec="seconds")})
