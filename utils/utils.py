import csv
from io import StringIO
from datetime import datetime
from typing import List, Dict


def generate_jobs_csv(jobs: List[Dict]) -> str:
    """
    Generate a CSV string from a list of job dictionaries.

    Args:
        jobs: List of job dictionaries containing job details.

    Returns:
        CSV string containing job data.
    """
    output = StringIO()
    if not jobs:
        return ""

    # Define CSV headers
    headers = [
        "id",
        "title",
        "company",
        "location",
        "remote_mode",
        "daily_salary",
        "published_at",
        "url",
    ]
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")

    # Write headers
    writer.writeheader()

    # Write job data
    for job in jobs:
        writer.writerow(
            {
                "id": job.get("id", ""),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "remote_mode": job.get("remote_mode", ""),
                "daily_salary": job.get("daily_salary", ""),
                "published_at": job.get("published_at", ""),
                "url": job.get("url", ""),
            }
        )

    csv_content = output.getvalue()
    output.close()
    return csv_content
