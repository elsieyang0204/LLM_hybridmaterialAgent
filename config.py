import os
from dotenv import load_dotenv

# 加载 .env
load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

class Config:
    # 数据库
    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USER = os.getenv("NEO4J_USERNAME")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    
    # API
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # LangSmith / LangChain tracing
    LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false")
    LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT")
    LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
    LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "default")

    # Retrieval policy
    DYNAMIC_CONSTRAINTS = _env_bool("DYNAMIC_CONSTRAINTS", True)
    
    # 路径配置
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    SYSTEM_PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "novel_candidate_prompt.txt")

# 实例化
config = Config()