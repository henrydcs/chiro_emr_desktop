# env_config.py
import os
from dotenv import load_dotenv

# Automatically loads .env from same folder or parent folders
load_dotenv()

def get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)