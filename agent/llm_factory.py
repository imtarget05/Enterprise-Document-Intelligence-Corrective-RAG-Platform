"""
LLM factory for the Ollama-compatible LLM Router service.

The router talks to Cloudflare Workers AI behind the scenes; this client speaks
the Ollama wire format to the router endpoint. Local tiers (2026-09-19):
LM Studio (OpenAI-compatible, DEFAULT when LOCAL_LMSTUDIO_URL is set —
qwen2.5-vl-3b-instruct for every task) takes priority over direct Ollama
(LOCAL_OLLAMA_URL — qwen2.5:3b for chat/RAG, qwen2.5-coder:1.5b for task=code).
"""

try:
    from langchain_ollama import ChatOllama
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
    except ImportError:
        class ChatOllama:  # type: ignore[no-redef]
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def invoke(self, *args, **kwargs):
                raise RuntimeError("langchain_ollama is not installed")

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    class ChatOpenAI:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def invoke(self, *args, **kwargs):
            raise RuntimeError("langchain_openai is not installed")

from langchain_community.chat_models import ChatOllama as RouterChatOllama

from settings import settings


class LLMFactory:
    CODE_TASKS = {"code"}

    @staticmethod
    def _lmstudio_enabled() -> bool:
        return bool(getattr(settings, "local_lmstudio_url", ""))

    @staticmethod
    def _local_enabled() -> bool:
        return bool(getattr(settings, "local_ollama_url", ""))

    @staticmethod
    def model_for_task(task: str = "chat") -> str:
        """Task routing: LM Studio single model first, else Ollama code/chat
        split, else cloud router model.
        """
        if LLMFactory._lmstudio_enabled():
            return settings.local_lmstudio_chat_model
        if LLMFactory._local_enabled():
            if (task or "chat").lower() in LLMFactory.CODE_TASKS:
                return settings.local_ollama_code_model
            return settings.local_ollama_chat_model
        return settings.llm_chat_model

    @staticmethod
    def get_reasoning_model(temperature: float = 0.3, task: str = "chat"):
        """Return the router client; the router selects the model for the task."""
        return LLMFactory.get_model(temperature, task)

    @staticmethod
    def get_model(temperature: float = 0.3, task: str = "chat"):
        """Return a chat client: LM Studio (OpenAI-compatible) when
        LOCAL_LMSTUDIO_URL is set, else ChatOllama at the local Ollama
        server when LOCAL_OLLAMA_URL is set, else at the cloud LLM Router."""
        if LLMFactory._lmstudio_enabled():
            return ChatOpenAI(
                base_url=settings.local_lmstudio_url.rstrip("/") + "/",
                api_key=getattr(settings, "local_lmstudio_api_key", "lm-studio"),
                model=LLMFactory.model_for_task(task),
                temperature=temperature,
            )
        if LLMFactory._local_enabled():
            return ChatOllama(
                base_url=settings.local_ollama_url,
                model=LLMFactory.model_for_task(task),
                temperature=temperature,
            )
        return RouterChatOllama(
            headers={"X-Internal-Token": settings.internal_service_token},
            base_url=settings.llm_base_url,
            model=settings.llm_chat_model,
            temperature=temperature,
        )