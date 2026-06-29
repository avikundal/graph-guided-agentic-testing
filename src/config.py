from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str | None = os.getenv("NEO4J_URI")
    neo4j_username: str | None = os.getenv("NEO4J_USERNAME")
    neo4j_password: str | None = os.getenv("NEO4J_PASSWORD")
    neo4j_database: str = os.getenv("NEO4J_DATABASE", "neo4j")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    target_product_url: str = os.getenv("TARGET_PRODUCT_URL", "https://www.amazon.com/dp/0307887898")

    @property
    def neo4j_enabled(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_username and self.neo4j_password)


settings = Settings()
