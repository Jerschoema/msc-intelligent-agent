"""Builds the chat model the agents share so it is simple to swap providers. 
"""

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from src.config.settings import settings


def _ollama() -> BaseChatModel:
    # reasoning=False suppresses qwen3's <think> blocks,
    #  which are not useful for our agents and make the output harder to read. 
    # We turn it on for the summarizer.
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        reasoning=False,
    )



_PROVIDERS = {
    "ollama": _ollama,
}


def get_llm() -> BaseChatModel:
    """Build the chat model named by LLM_PROVIDER.

    An unknown name raises right away (listing the valid ones) so a typo in .env is
    caught at startup instead of halfway through a run.
    """
    provider = settings.llm_provider
    try:
        return _PROVIDERS[provider]()
    except KeyError:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(
            f"Unknown LLM provider {provider!r}. Supported providers: {supported}."
        ) from None
