import os
import psycopg2
from dotenv import load_dotenv

def get_db_connection():
    """Establish and return a connection to the PostgreSQL database."""
    # Find .env by checking up the directory tree or defaulting to root
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    load_dotenv(env_path)

    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'mission-soil'),
        user=os.getenv('DB_USER', 'missionsoil_user'),
        password=os.getenv('DB_PASSWORD', '')
    )
