Lead Finder GMap – Local Business Lead Generation & SEO Intelligence

Discover local business opportunities, identify businesses with limited online visibility, and generate SEO performance reports.

Lead Finder GMap is a Python-based web application that helps freelancers, digital marketing agencies, web development agencies, and sales professionals discover potential business prospects using Google Maps data.

The application identifies businesses that do not have websites and businesses with comparatively lower review counts. It also provides competitor information and exports discovered leads into Excel.

Alongside lead discovery, the platform includes SEO analytics and PDF report generation using Google Search Console, Google Analytics 4, and DataForSEO.

⸻

Features

1. Google Maps Business Lead Finder

Discover potential customers by searching for a business category and geographical location.

* Search businesses by locality and category.
* Identify businesses without an official website.
* Retrieve publicly listed business phone numbers.
* View business addresses and Google Maps links.
* Identify competitors with existing websites.
* Export discovered leads to Excel.
* Compare businesses within the same category and locality.

2. Low Online Visibility Detection

Identify businesses that have an existing website but relatively lower customer review counts compared with other businesses in the same search results.

* Compare review counts across local businesses.
* Identify businesses below the average review count.
* Retrieve publicly listed phone numbers for identified prospects.
* View ratings, review counts, and website links.
* Compare against businesses with stronger review presence.

Note: This is a relative review-count comparison, not a comprehensive SEO or website-quality audit.

3. Competitor Discovery

Understand the local competitive landscape.

* Identify businesses already maintaining websites.
* View competitor website URLs.
* Compare local business presence.
* Use competitor information to identify potential digital marketing and website development opportunities.

4. Excel Lead Export

Export discovered business information into an Excel spreadsheet.

Available fields include:

* Business name
* Business category
* Location
* Phone number
* Business address
* Google Maps URL
* Competitor names
* Competitor website URLs

5. SEO Performance Reporting

Generate professional PDF reports using actual or estimated search performance data.

Integrations:

* Google Search Console
* Google Analytics 4
* DataForSEO

Reporting capabilities:

* Organic search impressions and clicks
* Average search position
* Organic sessions
* Average engagement duration
* Keyword ranking distribution
* Top 3 and Top 10 keyword comparisons
* AI Overview citation metrics
* Estimated organic revenue opportunity

Supports automated data retrieval and manual data entry.

6. Revenue Opportunity Estimation

Generate prospect-specific revenue opportunity reports using organic traffic estimates and configurable business assumptions.

The model supports:

* Organic traffic estimates
* Conversion-rate scenarios
* Average order value
* Configurable take rate
* Monthly and annual opportunity estimates

Modeled revenue is clearly distinguished from actual measured business revenue.

7. Deployment & Access Control

* Flask-based web application.
* Gunicorn deployment support.
* Render deployment configuration.
* Optional token-based application access.
* Server-side API key handling.

⸻

Technology Stack

Component	Technology
Backend	Python
Web Framework	Flask
Frontend	HTML, CSS, JavaScript
Business Discovery	Google Places API (New)
HTTP Requests	Requests
Excel Export	OpenPyXL
Browser Automation	Playwright
SEO Analytics	Google Search Console API
Website Analytics	Google Analytics Data API
SEO Intelligence	DataForSEO
PDF Generation	Playwright / Chromium
Deployment	Gunicorn, Render

⸻

Architecture

                  User
                    |
                    v
             Flask Web Application
                    |
          +---------+----------+
          |                    |
          v                    v
    Lead Finder            SEO Reporting
          |                    |
          v                    v
   Google Places API      Data Integrations
          |               /      |       \
          v              GSC     GA4    DataForSEO
   Business Results             |
          |                     v
          v                Report Builder
   Lead Classification          |
       /       \                 v
      /         \            PDF Report
 No Website   Low Visibility
      |         |
      +----+----+
           |
           v
      Competitor Data
           |
           v
      Excel Export

⸻

Project Structure

Lead_finder_gmap/
│
├── find_lead_map.py
│   └── Flask application and Google Maps lead finder
│
├── generate.py
│   └── CLI for SEO reports and revenue opportunity briefs
│
├── report_builder.py
│   └── PDF report generation engine
│
├── data_sources.py
│   └── Google Search Console, GA4 and DataForSEO integrations
│
├── traffic_estimate.py
│   └── Organic traffic estimation
│
├── requirements.txt
│   └── Python dependencies
│
├── Procfile
│   └── Production application startup configuration
│
├── build.sh
│   └── Deployment build script
│
├── render.yaml
│   └── Render deployment configuration
│
└── README.md

⸻

Getting Started

Prerequisites

* Python 3.10+
* pip
* Google Cloud account
* Google Places API (New) enabled
* Google Maps API key

Additional credentials are required only for the automated SEO reporting integrations.

1. Clone the Repository

git clone https://github.com/NewUserAyush/Lead_finder_gmap.git
cd Lead_finder_gmap

2. Create a Virtual Environment

macOS / Linux

python3 -m venv venv
source venv/bin/activate

Windows

python -m venv venv
venv\Scripts\activate

3. Install Dependencies

pip install -r requirements.txt

4. Install Playwright Chromium

playwright install chromium

5. Configure Google Maps API Key

Set your Google Maps API key as an environment variable.

macOS / Linux

export GOOGLE_MAPS_API_KEY="YOUR_GOOGLE_MAPS_API_KEY"

Windows PowerShell

$env:GOOGLE_MAPS_API_KEY="YOUR_GOOGLE_MAPS_API_KEY"

6. Start the Application

python find_lead_map.py

Open:

http://127.0.0.1:5000

⸻

Configuration

Google Maps Lead Finder

Environment Variable	Required	Description
GOOGLE_MAPS_API_KEY	Yes	Google Places API access
ACCESS_TOKEN	No	Optional application access protection

SEO Reporting Integrations

Environment Variable	Description
GOOGLE_APPLICATION_CREDENTIALS	Path to Google service-account JSON
DATAFORSEO_LOGIN	DataForSEO API login
DATAFORSEO_PASSWORD	DataForSEO API password

For Google Analytics and Search Console, configure a service account and grant it the required read-only access to the respective properties.

Never commit API keys, service-account credentials, or other secrets to GitHub.

⸻

API Endpoints

Business Lead Discovery

POST /api/search

Search businesses by location and category.

Example request:

{
  "place": "Bangalore",
  "category": "Dental Clinics",
  "search_type": "no_website"
}

Supported search types:

* no_website – Businesses without a website.
* low_visibility – Businesses with review counts below the search-result average.

Excel Export

POST /api/export

Generate an Excel file from previously retrieved lead and competitor results.

SEO PDF Report

POST /api/generate-report

Generate an SEO performance PDF using automatic or manual data.

Supported modes:

* auto – Retrieve available metrics through configured integrations.
* manual – Generate reports using supplied metrics.

⸻

SEO Report Generator – CLI Usage

The project also provides a command-line interface for generating SEO reports.

1. Generate a Prospect Report

Automatically estimate organic traffic through DataForSEO.

python3 generate.py prospect example.com \
  --currency inr \
  --aov 1500 \
  --take-rate 0.25 \
  --location 2356

Alternatively, provide traffic manually:

python3 generate.py prospect example.com \
  --currency inr \
  --aov 1500 \
  --visitors 12000

2. Generate a Before-and-After SEO Report

Create a starter configuration:

python3 generate.py results --template > client.json

Edit the JSON with the client’s performance data.

Generate the PDF:

python3 generate.py results client.json

3. Automated SEO Reporting

python3 generate.py results --auto client.json

Automated reporting requires the relevant Google credentials, DataForSEO credentials, and a properly configured client JSON file.

⸻

Deployment

The repository includes Render deployment configuration and a Gunicorn Procfile.

The configured application startup command is:

gunicorn --bind 0.0.0.0:$PORT find_lead_map:app

Set the required environment variables in the hosting platform before deployment.

For production, keep API credentials in the hosting provider’s secret/environment-variable configuration.

⸻

API Usage & Limitations

* Google Places API requires an enabled billing account and an appropriate API key.
* Search results are limited by the current implementation’s pagination settings.
* The current implementation requests up to two pages of 20 results per search.
* Phone number retrieval requires additional Places API requests.
* API usage and billing depend on the Google Places SKU and request volume.
* Low-visibility classification is based on relative review counts, not a verified SEO score.
* Search results may not include every business in a locality.

Monitor Google Cloud API usage and configure appropriate quotas and restrictions.

⸻

Responsible Usage

This application is intended for legitimate business research and lead discovery.

Users are responsible for:

* Following Google Maps Platform and Places API terms.
* Using business contact information responsibly.
* Complying with applicable privacy, data protection, and anti-spam regulations.
* Respecting API quotas and usage restrictions.
* Avoiding unsolicited or misleading communications.

⸻

Roadmap

Planned improvements:

* [ ]	Advanced business filtering and search controls.
* [ ]	Better lead qualification and prioritization.
* [ ]	Duplicate business detection.
* [ ]	Bulk location and category searches.
* [ ]	CRM integrations.
* [ ]	Lead history and saved searches.
* [ ]	Enhanced SEO and website audits.
* [ ]	Automated lead enrichment.
* [ ]	Automated test coverage.
* [ ]	Improved API usage monitoring and cost controls.

⸻

Contributing

Contributions, feature suggestions, and bug reports are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Implement your changes.
4. Test your changes locally.
5. Submit a pull request.

⸻

License

See the repository’s license file for licensing information.

⸻

Built by NewUserAyush

GitHub: https://github.com/NewUserAyush

Repository: https://github.com/NewUserAyush/Lead_finder_gmap
