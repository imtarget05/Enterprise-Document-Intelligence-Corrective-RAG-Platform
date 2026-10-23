from .config import Settings
from .models import ChatRequest, RouteDecision

COMPLEX_TASKS = {"compare", "summarize_long", "summarize"}


def infer_task_type(request: ChatRequest) -> str:
    if request.routing.task_type:
        return request.routing.task_type
    text = " ".join(
        m.content if isinstance(m.content, str) else ""
        for m in request.messages
    ).lower()
    if "compare" in text or "so sánh" in text:
        return "compare"
    if "summarize" in text or "summary" in text or "tóm tắt" in text:
        return "summarize"
    if "extract" in text or "trích xuất" in text:
        return "extract"
    if "code" in text or "```" in text or "viết code" in text or "lập trình" in text:
        return "code"
    return "qa"


def is_complex(request: ChatRequest) -> bool:
    task = infer_task_type(request)
    if task in COMPLEX_TASKS:
        return True
    if request.routing.page_count > 10:
        return True
    if request.routing.document_count is not None and request.routing.document_count > 2:
        return True
    return False


def choose_route(request: ChatRequest, settings: Settings, user_provider: str | None = None) -> RouteDecision:
    task_type = infer_task_type(request)

    # Use user-specified provider if provided (e.g., from API query param or header)
    if user_provider:
        provider = user_provider.lower()
        if provider == "ollama" or provider == "local":
            # Use local Ollama model
            return RouteDecision(
                model=settings.local_ollama_model,
                reason=f"user_selected:{provider}",
                task_type=task_type,
            )
        elif provider == "cloudflare" or provider == "workers_ai":
            # Use Cloudflare Workers AI
            return RouteDecision(
                model=settings.cloudflare_chat_model,
                reason=f"user_selected:{provider}",
                task_type=task_type,
            )
        # If provider is unrecognized, fall through to default logic

    if is_complex(request):
        return RouteDecision(
            model=settings.cloudflare_chat_model,
            reason=f"complex_task:{task_type}",
            task_type=task_type,
        )

    confidence = request.routing.confidence_score
    if confidence is not None and confidence < settings.confidence_threshold:
        return RouteDecision(
            model=settings.cloudflare_chat_model,
            reason=f"low_confidence:{confidence:.3f}",
            task_type=task_type,
        )

    return RouteDecision(
        model=settings.cloudflare_chat_model,
        reason=f"simple_task:{task_type}",
        task_type=task_type,
    )


def route_metadata(decision: RouteDecision, request_id: str) -> dict:
    return {"request_id": request_id, **decision.model_dump()}