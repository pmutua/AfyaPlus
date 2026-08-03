"""FastAPI entry point for the AfyaPlus RAG Agent System."""

from __future__ import annotations

from chainlit.utils import mount_chainlit
from fastapi import FastAPI, HTTPException, status
from langgraph.graph.state import CompiledStateGraph

from app.chat import production_agent, run_chat
from app.models import ChatRequest, ChatResponse, HealthResponse
from app.observability import install_api_observability
from app.safeguards.rate_limiting import (
    InMemoryRateLimiter,
    RateLimitSettings,
    install_chat_rate_limiting,
    load_rate_limit_settings,
)
from app.utils.logging import configure_logging


def create_app(
    agent: CompiledStateGraph | None = None,
    *,
    mount_ui: bool = True,
    rate_limit_settings: RateLimitSettings | None = None,
    rate_limiter: InMemoryRateLimiter | None = None,
) -> FastAPI:
    """Create the app with optional test agent and Chainlit UI mount."""

    configure_logging()
    chat_agent = agent or production_agent()
    application = FastAPI(title="AfyaPlus RAG Agent System", version="1.0.0")
    limits = rate_limit_settings or load_rate_limit_settings()
    install_chat_rate_limiting(application, limits, rate_limiter)
    install_api_observability(application)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        try:
            return run_chat(request, chat_agent)
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The AfyaPlus assistant is temporarily unavailable.",
            ) from error

    if mount_ui:
        mount_chainlit(
            app=application,
            target="app/chainlit_app.py",
            path="/ui",
        )

    return application


app = create_app()
