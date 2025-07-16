from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
import pytz
import os
import re
import logging
from dotenv import load_dotenv
from io import BytesIO
from utils.utils import generate_jobs_csv  # Updated import

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


class EmailSubmission(BaseModel):
    email: EmailStr


@app.get("/jobs/linkedin", response_class=HTMLResponse)
async def read_linkedin_jobs(
    request: Request,
    country: Optional[str] = None,
    continent: Optional[str] = None,
    date: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
):
    query = {}
    if country and country != "all":
        query["country"] = country
    if continent and continent != "all":
        query["continent"] = continent
    if date and date != "all":
        query["posting_time"] = {"$regex": f"^{date}", "$options": "i"}

    pipeline = [
        {"$match": query},
        {
            "$addFields": {
                "posting_time_dt": {
                    "$dateFromString": {
                        "dateString": "$posting_time",
                        "format": "%Y-%m-%d %H:%M:%S",
                    }
                }
            }
        },
        {"$sort": {"posting_time_dt": -1}},
        {"$project": {"posting_time_dt": 0}},
        {"$skip": (page - 1) * per_page},
        {"$limit": per_page},
    ]

    jobs = [doc async for doc in linkedin_collection.aggregate(pipeline)]
    total_jobs = await linkedin_collection.count_documents(query)
    total_pages = (total_jobs + per_page - 1) // per_page

    unique_countries = sorted(
        {
            doc["country"]
            async for doc in linkedin_collection.find({"country": {"$ne": None}})
        },
        key=lambda x: x or "",
    )
    unique_continents = sorted(
        {
            doc["continent"]
            async for doc in linkedin_collection.find({"continent": {"$ne": None}})
        },
        key=lambda x: x or "",
    )
    unique_dates = sorted(
        {
            doc["posting_time"][:10]
            async for doc in linkedin_collection.find({"posting_time": {"$ne": None}})
        },
        reverse=True,
    )

    return templates.TemplateResponse(
        "jobs/linkedin.html",
        {
            "request": request,
            "jobs": jobs,
            "unique_countries": unique_countries,
            "unique_continents": unique_continents,
            "unique_dates": unique_dates,
            "selected_country": country or "all",
            "selected_continent": continent or "all",
            "selected_date": date or "all",
            "total_jobs": total_jobs,
            "filtered_jobs_count": len(jobs),
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        },
    )


@app.get("/jobs/freework", response_class=HTMLResponse)
async def read_freework_jobs(
    request: Request,
    remote_mode: Optional[str] = None,
    date: Optional[str] = None,
    type: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
):
    query = {}
    if remote_mode and remote_mode != "all":
        query["remote_mode"] = remote_mode
    if date and date != "all":
        query["published_at"] = {"$regex": f"^{date}", "$options": "i"}
    if type == "scraping":
        query["scraping"] = True

    pipeline = [
        {"$match": query},
        {
            "$addFields": {
                "published_at_dt": {
                    "$dateFromString": {
                        "dateString": "$published_at",
                        "format": "%Y-%m-%dT%H:%M:%S%z",
                    }
                }
            }
        },
        {"$sort": {"published_at_dt": -1}},
        {"$project": {"published_at_dt": 0}},
        {"$skip": (page - 1) * per_page},
        {"$limit": per_page},
    ]

    jobs = [doc async for doc in freework_collection.aggregate(pipeline)]
    total_jobs = await freework_collection.count_documents(query)
    total_pages = (total_jobs + per_page - 1) // per_page

    unique_remote_modes = sorted(
        {
            doc["remote_mode"]
            async for doc in freework_collection.find({"remote_mode": {"$ne": None}})
        },
        key=lambda x: x or "",
    )
    unique_dates = sorted(
        {
            doc["published_at"][:10]
            async for doc in freework_collection.find({"published_at": {"$ne": None}})
        },
        reverse=True,
    )

    return templates.TemplateResponse(
        "jobs/freework.html",
        {
            "request": request,
            "jobs": jobs,
            "unique_remote_modes": unique_remote_modes,
            "unique_dates": unique_dates,
            "selected_remote_mode": remote_mode or "all",
            "selected_date": date or "all",
            "selected_type": type or "all",
            "total_jobs": total_jobs,
            "filtered_jobs_count": len(jobs),
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
