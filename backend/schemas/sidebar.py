from pydantic import BaseModel


class ChatCreateRequest(BaseModel):
    title: str | None = None


class ChatRenameRequest(BaseModel):
    title: str


class ChatMessageRequest(BaseModel):
    role: str = "user"
    content: str


class ChatTurnRequest(BaseModel):
    message: str
    agentic_enabled: bool = True


class MeetingRenameRequest(BaseModel):
    title: str