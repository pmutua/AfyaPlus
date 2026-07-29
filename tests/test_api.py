from typing import Any

from fastapi.testclient import TestClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from pydantic import PrivateAttr

from app.agent.agent import create_agent
from app.main import create_app

RAW_PII = ("AP-123456", "aisha@example.co.ke", "+254712345678")
MASKED_TOKENS = ("<<MEMBER_ID_3>>", "<<EMAIL_2>>", "<<PHONE_1>>")
USER_MESSAGE = (
    "Check member AP-123456, email aisha@example.co.ke, phone +254712345678."
)
MODEL_RESPONSE = (
    "Contact <<EMAIL_2>> at <<PHONE_1>> about member <<MEMBER_ID_3>>."
)
DISPLAYED_RESPONSE = (
    "Contact aisha@example.co.ke at +254712345678 about member AP-123456."
)


class RecordingFakeChatModel(FakeMessagesListChatModel):
    """Fake model that records the exact messages delivered to it."""

    _recorded_messages: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def recorded_messages(self) -> list[list[BaseMessage]]:
        return self._recorded_messages

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._recorded_messages.append(list(messages))
        return super()._generate(messages, stop, run_manager, **kwargs)


def test_health_endpoint_returns_ok() -> None:
    agent = create_agent(
        FakeMessagesListChatModel(responses=[AIMessage(content="Ready")]),
        [],
        "You are a test assistant.",
    )
    response = TestClient(create_app(agent, mount_ui=False)).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chainlit_ui_is_mounted() -> None:
    agent = create_agent(
        FakeMessagesListChatModel(responses=[AIMessage(content="Ready")]),
        [],
        "You are a test assistant.",
    )
    response = TestClient(create_app(agent)).get("/ui/", follow_redirects=False)

    assert response.status_code == 200


def test_chat_masks_model_input_and_demasks_final_response() -> None:
    model = RecordingFakeChatModel(
        responses=[AIMessage(content=MODEL_RESPONSE)]
    )
    agent = create_agent(model, [], "You are a test assistant.")
    client = TestClient(create_app(agent, mount_ui=False))

    response = client.post(
        "/chat",
        json={"message": USER_MESSAGE, "thread_id": "session-254"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "response": DISPLAYED_RESPONSE,
        "thread_id": "session-254",
    }
    model_input = " ".join(
        str(message.content) for message in model.recorded_messages[0]
    )
    for raw_pii in RAW_PII:
        assert raw_pii not in model_input
    for token in MASKED_TOKENS:
        assert token in model_input
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert (
        'afyaplus_api_http_requests_total{method="POST",route="/chat",'
        'status_class="2xx"} 1.0'
    ) in metrics.text
    for raw_pii in RAW_PII:
        assert raw_pii not in metrics.text


def test_chat_rejects_invalid_thread_id() -> None:
    agent = create_agent(
        FakeMessagesListChatModel(responses=[AIMessage(content="Ready")]),
        [],
        "You are a test assistant.",
    )
    response = TestClient(create_app(agent, mount_ui=False)).post(
        "/chat",
        json={"message": "Habari", "thread_id": "contains spaces"},
    )

    assert response.status_code == 422
