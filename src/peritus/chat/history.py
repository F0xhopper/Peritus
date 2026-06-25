from dataclasses import dataclass, field


@dataclass
class Turn:
    role: str   # "user" or "assistant"
    content: str


@dataclass
class ConversationHistory:
    turns: list[Turn] = field(default_factory=list)

    def add_user(self, content: str) -> None:
        self.turns.append(Turn(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        self.turns.append(Turn(role="assistant", content=content))

    def to_messages(self) -> list[dict]:
        return [{"role": t.role, "content": t.content} for t in self.turns]
