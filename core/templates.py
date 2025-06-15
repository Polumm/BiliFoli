# core/templates.py
from fastapi.templating import Jinja2Templates
from datetime import datetime
import urllib.parse

templates = Jinja2Templates(directory="templates")

def timestamp_to_date(value):
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return "Invalid date"

def format_duration(seconds):
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes:02}:{secs:02}"

def setup_jinja_filters():
    templates.env.filters["timestamp_to_date"] = timestamp_to_date
    templates.env.filters["format_duration"] = format_duration
    templates.env.filters["urlencode"] = lambda s: urllib.parse.quote_plus(s)

setup_jinja_filters()
