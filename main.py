from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta
import asyncio
import pytz
import os
import re
import logging
import time
import unicodedata
from dotenv import load_dotenv
from io import BytesIO
from utils.utils import generate_jobs_csv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()
# Use absolute path for static directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
# Use absolute path for templates directory
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


# Jinja2 custom filters
def datetimeformat(value, format="%B %d, %Y %I:%M %p"):
    if isinstance(value, dict) and "$date" in value:
        try:
            value = datetime.fromisoformat(value["$date"].replace("Z", "+00:00"))
        except ValueError as e:
            logger.error(f"Invalid $date format: {value['$date']}, {e}")
            return value
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.error(f"Invalid date format: {value}")
                return value
    return value.strftime(format)


def relative_time(value):
    if not value:
        logger.warning("No value provided to relative_time filter")
        return "Unknown"
    try:
        if isinstance(value, str):
            try:
                # Try LinkedIn format (YYYY-MM-DD HH:MM:SS, assume CEST)
                value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                value = pytz.timezone("Europe/Paris").localize(value)
            except ValueError:
                try:
                    # Try Freework format (YYYY-MM-DDTHH:MM:SS+ZZZZ)
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    logger.error(f"Invalid date format in relative_time: {value}")
                    return "Unknown"
        elif isinstance(value, dict) and "$date" in value:
            try:
                value = datetime.fromisoformat(value["$date"].replace("Z", "+00:00"))
            except ValueError:
                logger.error(f"Invalid $date format: {value['$date']}")
                return "Unknown"
        # Ensure timezone-aware in Europe/Paris
        if value.tzinfo is None:
            logger.warning(
                f"Timezone-naive date detected: {value}, assuming Europe/Paris"
            )
            value = pytz.timezone("Europe/Paris").localize(value)
        else:
            value = value.astimezone(pytz.timezone("Europe/Paris"))
        now = datetime.now(pytz.timezone("Europe/Paris"))
        # Cap future dates to now
        if value > now:
            logger.warning(f"Future date detected, capping to now: {value}")
            value = now
        delta = now - value
        seconds = delta.total_seconds()
        if seconds < 60:
            return "juste maintenant"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            return f"il y a {minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"il y a {hours} heure{'s' if hours != 1 else ''}"
        elif seconds < 2592000:  # 30 days
            days = int(seconds // 86400)
            return f"il y a {days} jour{'s' if days != 1 else ''}"
        else:
            months = int(seconds // 2592000)
            return f"il y a {months} moi{'s' if months != 1 else ''}"
    except Exception as e:
        logger.error(f"Error parsing date {value}: {str(e)}")
        return "Unknown"


templates.env.filters["datetimeformat"] = datetimeformat
templates.env.filters["relative_time"] = relative_time

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "scraping")
MONGO_COLLECTION_LINKEDIN = os.getenv("MONGO_COLLECTION_LINKEDIN", "linkedin")
MONGO_COLLECTION_FREEWORK = os.getenv("MONGO_COLLECTION_FREEWORK", "freework")
MONGO_COLLECTION_EMAIL = os.getenv("MONGO_COLLECTION_EMAIL", "emails")

if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable is not set")

# Validate MONGO_DB name
if not MONGO_DB or not re.match(r"^[a-zA-Z0-9_-]+$", MONGO_DB):
    raise ValueError(
        "MONGO_DB name is invalid; it must contain only letters, numbers, underscores, or hyphens"
    )

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]
linkedin_collection = db[MONGO_COLLECTION_LINKEDIN]
freework_collection = db[MONGO_COLLECTION_FREEWORK]
email_collection = db[MONGO_COLLECTION_EMAIL]

# Small in-memory cache for LinkedIn filter dropdowns.
LINKEDIN_FILTER_CACHE_TTL_SECONDS = int(
    os.getenv("LINKEDIN_FILTER_CACHE_TTL_SECONDS", "300")
)
_linkedin_filter_cache = {"expires_at": 0.0, "data": None}
FREEWORK_FILTER_CACHE_TTL_SECONDS = int(
    os.getenv("FREEWORK_FILTER_CACHE_TTL_SECONDS", "300")
)
_freework_filter_cache = {"expires_at": 0.0, "data": None}


class Job(BaseModel):
    url: str
    title: str
    company: str
    location: str
    posting_time: Optional[str] = None
    published_at: Optional[str] = None
    status: Optional[str] = None
    country: Optional[str] = None
    continent: Optional[str] = None
    remote_mode: Optional[str] = None
    daily_salary: Optional[str] = None
    source: Optional[str] = None  # Added source field


class EmailSubmission(BaseModel):
    email: EmailStr


def normalize_location_value(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized.replace("\n", " ").strip())
    return normalized if normalized else None


def extract_city_department_from_location(location: Optional[str]):
    normalized = normalize_location_value(location)
    if not normalized:
        return None, None
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return parts[0], None


async def get_linkedin_filter_options():
    now = time.monotonic()
    cached_data = _linkedin_filter_cache["data"]
    if cached_data and now < _linkedin_filter_cache["expires_at"]:
        return cached_data

    countries_task = linkedin_collection.distinct(
        "country", {"country": {"$nin": [None, ""]}}
    )
    continents_task = linkedin_collection.distinct(
        "continent", {"continent": {"$nin": [None, ""]}}
    )
    sources_task = linkedin_collection.distinct("source", {"source": {"$nin": [None, ""]}})
    date_cursor = linkedin_collection.aggregate(
        [
            {"$match": {"posting_time": {"$type": "string", "$nin": [""]}}},
            {"$project": {"date": {"$substrBytes": ["$posting_time", 0, 10]}}},
            {"$match": {"date": {"$regex": r"^\d{4}-\d{2}-\d{2}$"}}},
            {"$group": {"_id": "$date"}},
            {"$sort": {"_id": -1}},
        ]
    )

    countries, continents, sources, date_docs = await asyncio.gather(
        countries_task, continents_task, sources_task, date_cursor.to_list(length=None)
    )
    unique_dates = [doc["_id"] for doc in date_docs if doc.get("_id")]

    filter_options = {
        "unique_countries": sorted(countries, key=lambda x: x or ""),
        "unique_continents": sorted(continents, key=lambda x: x or ""),
        "unique_sources": sorted(sources, key=lambda x: x or ""),
        "unique_dates": unique_dates,
    }

    _linkedin_filter_cache["data"] = filter_options
    _linkedin_filter_cache["expires_at"] = now + LINKEDIN_FILTER_CACHE_TTL_SECONDS
    return filter_options


async def get_freework_filter_options():
    now = time.monotonic()
    cached_data = _freework_filter_cache["data"]
    if cached_data and now < _freework_filter_cache["expires_at"]:
        return cached_data

    remote_modes_task = freework_collection.distinct(
        "remote_mode", {"remote_mode": {"$nin": [None, ""]}}
    )
    departments_task = freework_collection.distinct(
        "department", {"department": {"$nin": [None, ""]}}
    )
    cities_task = freework_collection.distinct("city", {"city": {"$nin": [None, ""]}})
    date_cursor = freework_collection.aggregate(
        [
            {"$match": {"published_at": {"$type": "string", "$nin": [""]}}},
            {"$project": {"date": {"$substrBytes": ["$published_at", 0, 10]}}},
            {"$match": {"date": {"$regex": r"^\d{4}-\d{2}-\d{2}$"}}},
            {"$group": {"_id": "$date"}},
            {"$sort": {"_id": -1}},
        ]
    )
    remote_modes, departments, cities, date_docs = await asyncio.gather(
        remote_modes_task,
        departments_task,
        cities_task,
        date_cursor.to_list(length=None),
    )
    unique_dates = [doc["_id"] for doc in date_docs if doc.get("_id")]
    cleaned_departments = sorted(
        {
            normalize_location_value(department)
            for department in departments
            if normalize_location_value(department)
        },
        key=lambda x: x.lower(),
    )
    cleaned_cities = sorted(
        {
            normalize_location_value(city)
            for city in cities
            if normalize_location_value(city)
        },
        key=lambda x: x.lower(),
    )

    filter_options = {
        "unique_remote_modes": sorted(remote_modes, key=lambda x: x or ""),
        "unique_dates": unique_dates,
        "unique_departments": cleaned_departments,
        "unique_cities": cleaned_cities,
    }

    _freework_filter_cache["data"] = filter_options
    _freework_filter_cache["expires_at"] = now + FREEWORK_FILTER_CACHE_TTL_SECONDS
    return filter_options


@app.get("/jobs/linkedin", response_class=HTMLResponse)
async def read_linkedin_jobs(
    request: Request,
    country: Optional[str] = None,
    continent: Optional[str] = None,
    date: Optional[str] = None,
    source: Optional[str] = None,  # Added source parameter
    page: int = 1,
    per_page: int = 20,
):
    page = max(page, 1)
    per_page = max(min(per_page, 100), 1)

    query = {}
    if country and country != "all":
        query["country"] = country
    if continent and continent != "all":
        query["continent"] = continent
    if date and date != "all":
        try:
            date_start = datetime.strptime(date, "%Y-%m-%d")
            date_end = date_start + timedelta(days=1)
            query["posting_time"] = {
                "$gte": f"{date_start.strftime('%Y-%m-%d')} 00:00:00",
                "$lt": f"{date_end.strftime('%Y-%m-%d')} 00:00:00",
            }
        except ValueError:
            logger.warning(f"Invalid date filter format: {date}")
            query["posting_time"] = {"$regex": f"^{date}", "$options": "i"}
    if source and source != "all":  # Apply source filter
        query["source"] = source

    projection = {
        "_id": 0,
        "url": 1,
        "title": 1,
        "company": 1,
        "location": 1,
        "posting_time": 1,
        "country": 1,
        "continent": 1,
        "source": 1,
    }
    total_jobs_task = linkedin_collection.count_documents(query)
    filters_task = get_linkedin_filter_options()
    total_jobs, filters = await asyncio.gather(total_jobs_task, filters_task)
    total_pages = max((total_jobs + per_page - 1) // per_page, 1)
    page = min(page, total_pages)

    jobs = await (
        linkedin_collection.find(query, projection)
        .sort("posting_time", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
        .to_list(length=per_page)
    )

    return templates.TemplateResponse(
        "jobs/linkedin.html",
        {
            "request": request,
            "jobs": jobs,
            "unique_countries": filters["unique_countries"],
            "unique_continents": filters["unique_continents"],
            "unique_dates": filters["unique_dates"],
            "unique_sources": filters["unique_sources"],  # Pass unique sources
            "selected_country": country or "all",
            "selected_continent": continent or "all",
            "selected_date": date or "all",
            "selected_source": source or "all",  # Pass selected source
            "total_jobs": total_jobs,
            "filtered_jobs_count": total_jobs,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        },
    )


# The rest of your app.py remains unchanged
# Including other routes like /jobs/freework, /jobs/freework/download-today-with-email, etc.
@app.get("/jobs/freework", response_class=HTMLResponse)
async def read_freework_jobs(
    request: Request,
    remote_mode: Optional[str] = None,
    date: Optional[str] = None,
    type: Optional[str] = None,
    department: Optional[str] = None,
    city: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
):
    page = max(page, 1)
    per_page = max(min(per_page, 100), 1)

    query = {}
    if remote_mode and remote_mode != "all":
        query["remote_mode"] = remote_mode
    if date and date != "all":
        query["published_at"] = {"$regex": f"^{date}"}
    if type == "scraping":
        query["scraping"] = True
    if department and department != "all":
        normalized_department = normalize_location_value(department)
        if normalized_department:
            query["department"] = {"$regex": f"^{re.escape(normalized_department)}$", "$options": "i"}
    if city and city != "all":
        normalized_city = normalize_location_value(city)
        if normalized_city:
            query["city"] = {"$regex": f"^{re.escape(normalized_city)}$", "$options": "i"}

    projection = {
        "_id": 0,
        "id": 1,
        "title": 1,
        "company": 1,
        "location": 1,
        "url": 1,
        "published_at": 1,
        "remote_mode": 1,
        "daily_salary": 1,
        "department": 1,
        "city": 1,
    }
    total_jobs_task = freework_collection.count_documents(query)
    filters_task = get_freework_filter_options()
    total_jobs, filters = await asyncio.gather(total_jobs_task, filters_task)
    total_pages = max((total_jobs + per_page - 1) // per_page, 1)
    page = min(page, total_pages)

    jobs = await (
        freework_collection.find(query, projection)
        .sort("published_at", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
        .to_list(length=per_page)
    )
    for job in jobs:
        city_from_location, department_from_location = extract_city_department_from_location(
            job.get("location")
        )
        job["city"] = normalize_location_value(job.get("city")) or city_from_location
        job["department"] = normalize_location_value(job.get("department")) or department_from_location

    return templates.TemplateResponse(
        "jobs/freework.html",
        {
            "request": request,
            "jobs": jobs,
            "unique_remote_modes": filters["unique_remote_modes"],
            "unique_dates": filters["unique_dates"],
            "unique_departments": filters["unique_departments"],
            "unique_cities": filters["unique_cities"],
            "selected_remote_mode": remote_mode or "all",
            "selected_date": date or "all",
            "selected_type": type or "all",
            "selected_department": normalize_location_value(department) if department else "all",
            "selected_city": normalize_location_value(city) if city else "all",
            "total_jobs": total_jobs,
            "filtered_jobs_count": total_jobs,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        },
    )


@app.post("/jobs/freework/download-today-with-email")
async def download_freework_jobs_today_with_email(email: str = Form(...)):
    # Validate email format
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_regex, email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    # Save email to MongoDB
    try:
        await email_collection.insert_one(
            {
                "email": email,
                "timestamp": datetime.now(pytz.timezone("Europe/Paris")).isoformat(),
            }
        )
    except Exception as e:
        logger.error(f"Failed to save email to MongoDB: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save email")

    # Get current date in YYYY-MM-DD format (Europe/Paris timezone)
    today = datetime.now(pytz.timezone("Europe/Paris")).strftime("%Y-%m-%d")

    # Query for jobs published today
    query = {"published_at": {"$regex": f"^{today}", "$options": "i"}}
    jobs = [doc async for doc in freework_collection.find(query)]

    # Generate CSV content
    csv_content = generate_jobs_csv(jobs)

    if not csv_content:
        raise HTTPException(status_code=404, detail="No jobs found for today")

    # Prepare response with CSV content
    return StreamingResponse(
        content=BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="freework_jobs_{today}.csv"'
        },
    )


@app.get("/jobs/freework/{job_id}", response_class=HTMLResponse)
async def read_freework_job_detail(request: Request, job_id: str, return_page: int = 1):
    try:
        job = await freework_collection.find_one({"id": int(job_id)})
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    similar_jobs = [
        doc
        async for doc in freework_collection.find(
            {"remote_mode": job.get("remote_mode"), "id": {"$ne": job["id"]}}
        ).limit(3)
    ]

    return templates.TemplateResponse(
        "jobs/freework_detail.html",
        {
            "request": request,
            "job": job,
            "similar_jobs": similar_jobs,
            "return_page": return_page,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "current_year": datetime.now().year}
    )


@app.get("/intro", response_class=HTMLResponse)
async def intro(request: Request):
    return templates.TemplateResponse("intro.html", {"request": request})


@app.get("/index", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "current_year": datetime.now().year}
    )


@app.get("/resume", response_class=HTMLResponse)
async def resume(request: Request):
    return templates.TemplateResponse("resume.html", {"request": request})


@app.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.get("/projects", response_class=HTMLResponse)
async def projects(request: Request):
    return templates.TemplateResponse("projects.html", {"request": request})
