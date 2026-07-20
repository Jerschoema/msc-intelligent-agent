import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back safely on bad input
    to keep the program running.

    """
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    """Central configuration, set once at startup.

    Every field reads from the environment with a default

    """

    
    # qwen3:4b the ResearchAgent needs native tool calling
   
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen3:4b"))
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "ollama"))

    # Optional
    semanticscholar_api_key: str = field(default_factory=lambda: os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""))

    # Optional: URL of a running GROBID server (e.g. http://localhost:8070 via
    # I have not tested grobid yet.
    grobid_url: str = field(default_factory=lambda: os.getenv("GROBID_URL", ""))

    # --- Retrieval / sources ---
    # Results per engine per query to improve latency and only return the most relevant sources.
    search_max_results: int = field(default_factory=lambda: _env_int("SEARCH_MAX_RESULTS", 5))
    chunk_size: int = field(default_factory=lambda: _env_int("CHUNK_SIZE", 1000))
    chunk_overlap: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP", 150))
    top_k: int = field(default_factory=lambda: _env_int("TOP_K", 4))


    # If you want to limit the search to recent papers.
    min_year: int = field(default_factory=lambda: _env_int("MIN_YEAR", 0))

    # Path to output folder
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))

    # Agent loops
    max_loops: int = field(default_factory=lambda: _env_int("MAX_LOOPS", 5))

    # Limit for researcher's ReAct loop 
    agent_max_steps: int = field(default_factory=lambda: _env_int("AGENT_MAX_STEPS", 12))


settings = Settings()


def enable_deep_mode() -> None:
    """Switch the run from brief to deep research.
    """
    settings.search_max_results = 10  
    settings.agent_max_steps = 40  
    settings.max_loops = 10  

