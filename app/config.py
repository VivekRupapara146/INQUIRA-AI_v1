"""
Centralized, typed configuration. Everything environment-dependent lives here
so agents/tools never read os.environ directly (keeps them testable/mockable).
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM provider ---
    llm_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- Search / tools ---
    tavily_api_key: str = ""
    max_tavily_results: int = 5
    max_arxiv_results: int = 5
    max_subquestions_per_batch: int = 3  # how many sub-questions to search per
                                          # tool_executor pass -- both the first
                                          # pass AND any confidence-loop retry
                                          # pull from this batch size (see graph.py
                                          # subquestion_offset for how retries get
                                          # NEW sub-questions instead of repeats)

    # --- Agent behavior ---
    max_research_iterations: int = 2   # how many times reasoner can request more evidence
    request_timeout_seconds: int = 20

    # --- Storage ---
    sqlite_path: str = "./inquira.db"

    # --- App ---
    app_env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton -- avoids re-parsing .env on every import."""
    return Settings()
