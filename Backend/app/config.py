import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional
    pass

DB_PATH = os.getenv("DB_PATH", "data/jobs.db")
COMPANIES_FILE = os.getenv("COMPANIES_FILE", "companies.yaml")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")