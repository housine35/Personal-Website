Job Listing App
A web application built with FastAPI and MongoDB to display job listings scraped from LinkedIn and Freework. The app provides a user-friendly interface to filter and browse job opportunities, with relative time display in French (e.g., "il y a 41 minutes") using the Europe/Paris timezone (CEST). Features include filtering LinkedIn jobs by country, continent, and posting date, and Freework jobs by remote mode and publication date.
Table of Contents

Features
Technologies
Prerequisites
Setup
Running the Application
Deployment
Project Structure
MongoDB Configuration
Troubleshooting
Contributing
License

Features

LinkedIn Jobs:
Browse job listings with filters for country, continent, and posting date.
Displays job title, company, location, and relative posting time (e.g., "il y a 2 heures").
Pagination and results-per-page options (10, 20, 50, 100).


Freework Jobs:
Browse job listings with filters for remote mode and publication date.
View detailed job pages with similar job suggestions.
Pagination support.


Responsive UI: Built with Tailwind CSS, Google Fonts (Inter), and Font Awesome for a modern, user-friendly interface.
Timezone Handling: All LinkedIn job posting times are displayed relative to the current time in Europe/Paris (CEST).
Docker Support: Containerized for easy deployment.
MongoDB Integration: Stores job data in MongoDB Atlas for efficient querying.

Technologies

Backend: FastAPI, Python 3.10
Frontend: Jinja2 templates, Tailwind CSS, Font Awesome, Google Fonts
Database: MongoDB Atlas
Dependencies: fastapi, uvicorn, motor, python-dotenv, jinja2
Containerization: Docker
Deployment: Render (optional)

Prerequisites

Python: 3.10 or higher
Docker: Installed for containerized deployment
MongoDB Atlas: A MongoDB Atlas account with a cluster and database (scraping) containing linkedin and freework collections
Git: For cloning the repository

Setup

Clone the Repository:
git clone https://github.com/your-username/job-listing-app.git
cd job-listing-app


Set Up MongoDB Atlas:

Create a MongoDB Atlas cluster.
Create a database named scraping with two collections: linkedin and freework.
Whitelist your IP address (or 0.0.0.0/0 for testing) in the Atlas Network Access settings.
Obtain your MongoDB connection URI (e.g., mongodb+srv://<username>:<password>@cluster0.ypgrqjo.mongodb.net/scraping?retryWrites=true&w=majority).


Create .env File:Create a .env file in the project root with the following:
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.ypgrqjo.mongodb.net/scraping?retryWrites=true&w=majority
MONGO_DB=scraping
MONGO_COLLECTION_LINKEDIN=linkedin
MONGO_COLLECTION_FREEWORK=freework

Replace <username> and <password> with your MongoDB Atlas credentials.

Install Dependencies (for local development):
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt



Running the Application
Local Development

Start the FastAPI server:
python app/main.py

Or use Uvicorn directly:
uvicorn app.main:app --host 0.0.0.0 --port 8000


Open your browser and navigate to http://localhost:8000.


Docker

Build the Docker image:
docker build -t job-listing-app .


Run the Docker container:
docker run --env-file .env -p 8000:8000 job-listing-app


Access the app at http://localhost:8000.


Deployment
Render

Push the repository to GitHub:
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/your-username/job-listing-app.git
git branch -M main
git push -u origin main


Create a Web Service on Render:

Select your repository.
Choose Docker as the runtime.
Add environment variables in Render’s dashboard:MONGO_URI=mongodb+srv://<username>:<password>@cluster0.ypgrqjo.mongodb.net/scraping?retryWrites=true&w=majority
MONGO_DB=scraping
MONGO_COLLECTION_LINKEDIN=linkedin
MONGO_COLLECTION_FREEWORK=freework


Remove COPY .env . from Dockerfile before pushing to GitHub.
Deploy the service.


Access the deployed app via the Render-provided URL.


Project Structure
├── app
│   ├── main.py                # FastAPI application with routes and custom filters
│   ├── static
│   │   ├── css
│   │   │   └── style.css     # Custom CSS styles
│   │   └── image             # Static images
│   └── templates
│       ├── contact.html      # Contact page
│       ├── index.html        # Index page
│       ├── intro.html        # Home page
│       ├── jobs
│       │   ├── freework_detail.html  # Freework job detail page
│       │   ├── freework.html        # Freework jobs listing
│       │   └── linkedin.html        # LinkedIn jobs listing
│       ├── partials
│       │   ├── footer.html   # Footer template
│       │   └── navbar.html   # Navigation bar template
│       ├── projects.html     # Projects page
│       └── resume.html       # Resume page
├── Dockerfile                # Docker configuration
├── requirements.txt          # Python dependencies
└── .env                     # Environment variables (not included in Git)

MongoDB Configuration

Collections:
linkedin: Stores LinkedIn job data with fields like url, title, company, location, posting_time (format: YYYY-MM-DD HH:MM:SS), country, continent.
freework: Stores Freework job data with fields like url, title, company, location, published_at (format: YYYY-MM-DDTHH:MM:SS+ZZZZ), remote_mode, daily_salary.


Indexes (recommended for performance):db.linkedin.createIndex({ "country": 1 });
db.linkedin.createIndex({ "continent": 1 });
db.linkedin.createIndex({ "posting_time": 1 });
db.freework.createIndex({ "remote_mode": 1 });
db.freework.createIndex({ "published_at": 1 });
db.freework.createIndex({ "id": 1 });



Troubleshooting

Incorrect Time Display:
Check posting_time values in MongoDB:db.linkedin.find({}, { "posting_time": 1, "title": 1, "_id": 0 }).sort({ "posting_time": -1 }).limit(10);


Ensure posting_time is in YYYY-MM-DD HH:MM:SS format and not in the future.
Verify Docker container’s timezone:docker run -it job-listing-app python -c "from datetime import datetime; import pytz; print(datetime.now(pytz.timezone('Europe/Paris')))"




MongoDB Connection Issues:
Verify MONGO_URI in .env.
Ensure your IP is whitelisted in MongoDB Atlas.


Logs:
Check Docker logs for errors:docker ps -a
docker logs <container_id>





Contributing
Contributions are welcome! Please:

Fork the repository.
Create a feature branch (git checkout -b feature/your-feature).
Commit your changes (git commit -m "Add your feature").
Push to the branch (git push origin feature/your-feature).
Open a pull request.

License
This project is licensed under the MIT License.