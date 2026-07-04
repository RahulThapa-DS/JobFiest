import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("JobFiest Server")

# Simulated databases
JOBS_DB = [
    {
        "title": "Software Engineer",
        "company": "TechCorp",
        "location": "San Francisco",
        "description": "Develop and maintain core products. Experience with Python/Go preferred.",
        "url": "https://techcorp.jobs/se"
    },
    {
        "title": "Senior Frontend Developer",
        "company": "DesignHub",
        "location": "Remote",
        "description": "Lead the UI development for our next-gen SaaS platform. Expert React skills required.",
        "url": "https://designhub.jobs/sr-frontend"
    },
    {
        "title": "Data Scientist",
        "company": "DataInsights",
        "location": "New York",
        "description": "Build ML models and analyze large datasets. Python, SQL, and PyTorch required.",
        "url": "https://datainsights.jobs/ds"
    },
    {
        "title": "Product Manager",
        "company": "Gigasoft",
        "location": "San Francisco",
        "description": "Define product roadmap and collaborate with engineering and design.",
        "url": "https://gigasoft.jobs/pm"
    },
    {
        "title": "DevOps Engineer",
        "company": "CloudScale",
        "location": "Remote",
        "description": "Manage AWS infrastructure and Kubernetes clusters. Terraform knowledge a must.",
        "url": "https://cloudscale.jobs/devops"
    }
]

REVIEWS_DB = {
    "techcorp": {"rating": 4.2, "reviews": ["Great culture and work-life balance.", "Fast-paced environment but very rewarding."]},
    "designhub": {"rating": 4.5, "reviews": ["Flexible remote-first culture.", "Great design team but slower career progression."]},
    "datainsights": {"rating": 3.8, "reviews": ["High salary but long hours.", "Interesting data challenges but heavy legacy tech."]},
    "gigasoft": {"rating": 4.0, "reviews": ["Smart colleagues and high budget.", "Standard big corporate bureaucracy."]},
    "cloudscale": {"rating": 4.4, "reviews": ["Super friendly startup vibes.", "Unlimited PTO that people actually take."]}
}

SALARY_DB = {
    "software engineer": {"min": 110000, "max": 160000, "currency": "USD"},
    "frontend developer": {"min": 90000, "max": 140000, "currency": "USD"},
    "data scientist": {"min": 120000, "max": 175000, "currency": "USD"},
    "product manager": {"min": 115000, "max": 170000, "currency": "USD"},
    "devops engineer": {"min": 105000, "max": 155000, "currency": "USD"}
}

@mcp.tool()
def search_jobs(title: str, location: str) -> str:
    """Search for jobs matching title and location.

    Args:
        title: The job title keyword to search for (e.g. Software Engineer, Frontend).
        location: Location preference (e.g. Remote, San Francisco, New York). Use 'Anywhere' to not filter by location.
    """
    results = []
    title_lower = title.lower()
    loc_lower = location.lower()
    
    for job in JOBS_DB:
        # Match title
        title_match = title_lower in job["title"].lower() or any(w in job["title"].lower() for w in title_lower.split())
        
        # Match location
        if loc_lower == "anywhere" or not location:
            loc_match = True
        else:
            loc_match = loc_lower in job["location"].lower()
            
        if title_match and loc_match:
            results.append(job)
            
    return json.dumps(results, indent=2)

@mcp.tool()
def get_company_reviews(company: str) -> str:
    """Get employee reviews and rating for a company.

    Args:
        company: The name of the company to query.
    """
    key = company.lower().replace(" ", "")
    reviews_data = REVIEWS_DB.get(key, {"rating": "N/A", "reviews": ["No reviews available yet for this company."]})
    return json.dumps(reviews_data, indent=2)

@mcp.tool()
def get_salary_range(title: str, location: str) -> str:
    """Get market salary estimates for a job title and location.

    Args:
        title: The job title.
        location: The location of the job.
    """
    title_lower = title.lower()
    match = None
    for k, v in SALARY_DB.items():
        if k in title_lower:
            match = v
            break
            
    if not match:
        match = {"min": 80000, "max": 130000, "currency": "USD"} # default estimation
        
    # Apply location factor (SF and NY are higher)
    loc_lower = location.lower()
    factor = 1.0
    if "san francisco" in loc_lower or "sf" in loc_lower:
        factor = 1.25
    elif "new york" in loc_lower or "ny" in loc_lower:
        factor = 1.20
    elif "remote" in loc_lower:
        factor = 1.05
        
    estimated_range = {
        "title": title,
        "location": location,
        "min_salary": int(match["min"] * factor),
        "max_salary": int(match["max"] * factor),
        "currency": match["currency"]
    }
    return json.dumps(estimated_range, indent=2)

@mcp.tool()
def check_commute_time(destination: str, starting_from: str) -> str:
    """Estimate commute time and distance to a destination office location.

    Args:
        destination: Job location or office address.
        starting_from: Candidate's residential area or current city.
    """
    dest_lower = destination.lower()
    start_lower = starting_from.lower()
    
    if "remote" in dest_lower:
        return json.dumps({"transit_time_minutes": 0, "distance_miles": 0, "mode": "None", "notes": "No commute required (Remote role)"})
        
    if dest_lower == start_lower or dest_lower in start_lower or start_lower in dest_lower:
        return json.dumps({"transit_time_minutes": 20, "distance_miles": 5.2, "mode": "Car / Public Transit", "notes": "Local commute"})
        
    # Simulated commute across cities
    return json.dumps({
        "transit_time_minutes": 45,
        "distance_miles": 18.5,
        "mode": "Train / Highway",
        "notes": "Moderate commute, daily travel recommended"
    })

if __name__ == "__main__":
    mcp.run(transport="stdio")
