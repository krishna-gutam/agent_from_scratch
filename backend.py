"""
backend.py
----------
The session layer. It wraps the existing CLI module (`main.py`) and holds all
conversation state, tool orchestration and persistence. It imports no UI
library, so swapping Streamlit for a TUI means rewriting `app.py` only.

`main.py` is imported unchanged. Everything in it lives behind function
definitions or an `if __name__ == "__main__"` guard, so importing it only
runs `load_dotenv()`.
"""

import json
import os
import uuid
from dataclasses import dataclass, field

import main as core
from tools import TOOLS, execute_tool
import skills as skills_mod

CHATS_DIR = "chats"
CATALOG_FILE = "discovered_models.json"


# --- HELPERS ----------------------------------------------------------------


def sanitize_content(text) -> str:
    """Stop stray dollar signs from being swallowed as LaTeX by st.markdown."""
    if not isinstance(text, str):
        text = str(text)
    return text.replace("$", "\\$")


def estimate_tokens(messages) -> int:
    """Rough char/4 estimate. The chat endpoints here return no usage block."""
    return sum(len(json.dumps(m, default=str)) for m in messages) // 4


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)

    @property
    def display_args(self) -> dict:
        return self.args or {"(no arguments)": ""}


# --- MODEL CATALOG ----------------------------------------------------------


def refresh_catalog() -> None:
    """Re-query every provider. Writes discovered_models.json."""
    core.discover_models()


def load_catalog() -> dict:
    if not os.path.exists(CATALOG_FILE):
        core.discover_models()
    return core.load_models()


def search_catalog(query: str = ""):
    """Returns a list of (provider, model) tuples, best match first."""
    try:
        return core.search_models(load_catalog(), query)
    except SystemExit:
        return []


def provider_ready(provider: str) -> bool:
    config = core.CONFIGS.get(provider)
    return bool(config and os.getenv(config["api_key_env"]))


# --- SESSION ----------------------------------------------------------------


class ChatSession:
    """One conversation thread against one model."""

    def __init__(self, thread_id: str | None = None):
        os.makedirs(CHATS_DIR, exist_ok=True)
        self.provider: str | None = None
        self.model: str | None = None
        self.messages: list[dict] = []
        self.pending: list[ToolCall] = []
        self.busy = False            # a model call is owed
        self.tools_enabled = True
        self.last_error: str | None = None
        self.thread_id = thread_id or self._new_id()
        self._load()

    # --- identity -----------------------------------------------------------

    @staticmethod
    def _new_id() -> str:
        return uuid.uuid4().hex[:8]

    def _path(self, thread_id: str | None = None) -> str:
        return os.path.join(CHATS_DIR, f"{thread_id or self.thread_id}.json")

    def is_ready(self) -> bool:
        return bool(self.provider and self.model and provider_ready(self.provider))

    def set_model(self, provider: str, model: str) -> None:
        self.provider, self.model = provider, model
        self._save()

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.messages)

    # --- persistence --------------------------------------------------------

    def _save(self) -> None:
        payload = {
            "provider": self.provider,
            "model": self.model,
            "busy": self.busy,
            "messages": self.messages,
        }
        with open(self._path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)

    def _load(self) -> None:
        if not os.path.exists(self._path()):
            return
        try:
            with open(self._path(), "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return
        self.provider = payload.get("provider")
        self.model = payload.get("model")
        self.messages = payload.get("messages", [])
        self.busy = payload.get("busy", False)
        self._rehydrate_pending()

    def _rehydrate_pending(self) -> None:
        """Rebuild the approval gate if we were reloaded mid tool call."""
        self.pending = []
        if not self.messages:
            return
        last = self.messages[-1]
        if last.get("role") == "assistant" and last.get("tool_calls"):
            self.pending = self._to_tool_calls(last["tool_calls"])

    # --- threads ------------------------------------------------------------

    def list_threads(self) -> list[str]:
        names = sorted(
            f[:-5] for f in os.listdir(CHATS_DIR) if f.endswith(".json")
        )
        if self.thread_id not in names:
            names.append(self.thread_id)
        return names

    def switch_thread(self, thread_id: str) -> None:
        self._save()
        provider, model = self.provider, self.model
        self.thread_id = thread_id
        self.messages, self.pending, self.busy = [], [], False
        self._load()
        # Keep the current model when opening a thread that never picked one.
        self.provider = self.provider or provider
        self.model = self.model or model

    def new_thread(self, thread_id: str | None = None) -> None:
        self._save()
        self.thread_id = thread_id or self._new_id()
        self.messages, self.pending, self.busy, self.last_error = [], [], False, None
        self._save()

    def delete_thread(self, thread_id: str) -> None:
        path = self._path(thread_id)
        if os.path.exists(path):
            os.remove(path)
        if thread_id == self.thread_id:
            self.new_thread()

    def thread_summary(self, thread_id: str) -> dict:
        try:
            with open(self._path(thread_id), "r", encoding="utf-8") as f:
                messages = json.load(f).get("messages", [])
        except Exception:
            messages = []
        last_human = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        last_ai = next(
            (
                m.get("content") or "[tool call]"
                for m in reversed(messages)
                if m.get("role") == "assistant"
            ),
            "",
        )
        return {"last_human": last_human, "last_ai": last_ai, "count": len(messages)}

    # --- history editing ----------------------------------------------------

    def clear_history(self) -> None:
        self.messages, self.pending, self.busy, self.last_error = [], [], False, None
        self._save()

    def undo_last_turn(self) -> bool:
        """Drop everything back to and including the most recent user turn."""
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                self.messages = self.messages[:i]
                self.pending, self.busy = [], False
                self._save()
                return True
        return False

    def undo_first_turn(self) -> bool:
        """Drop the oldest user turn and everything up to the next one."""
        starts = [i for i, m in enumerate(self.messages) if m.get("role") == "user"]
        if not starts:
            return False
        cut = starts[1] if len(starts) > 1 else len(self.messages)
        self.messages = self.messages[cut:]
        self._rehydrate_pending()
        self._save()
        return True

    def delete_message(self, index: int) -> bool:
        if 0 <= index < len(self.messages):
            self.messages.pop(index)
            self.busy = False
            self._rehydrate_pending()
            self._save()
            return True
        return False

    # --- skills -------------------------------------------------------------

    @staticmethod
    def skill_catalog() -> list[dict]:
        return [skills_mod.discover_skills()[k] for k in sorted(skills_mod.discover_skills())]

    @staticmethod
    def reload_skills() -> None:
        skills_mod.discover_skills(force=True)

    @staticmethod
    def expand_skill(name: str, task: str = "") -> str | None:
        skill, _candidates = skills_mod.resolve(name)
        return skills_mod.render(skill, task.strip()) if skill else None

    def _handle_skill_command(self, text: str):
        """Returns (expanded_prompt, note). Exactly one is not None."""
        parts = text.split(maxsplit=1)
        rest = parts[1].strip() if len(parts) > 1 else ""

        if rest.lower() in ("reload", "refresh"):
            self.reload_skills()
            return None, "Skills reloaded.\n\n" + skills_mod.format_catalog()
        if parts[0].lower() == "/skills" or not rest:
            return None, skills_mod.format_catalog()

        name, _, task = rest.partition(" ")
        expanded = self.expand_skill(name, task)
        if expanded is None:
            return None, f"No skill named '{name}'.\n\n" + skills_mod.format_catalog()
        return expanded, None

    # --- input --------------------------------------------------------------

    def submit(self, text: str) -> str | None:
        """Accept one line of user input. Returns a note to show, or None.

        Understands the same '!cmd', '!!cmd' and '/skill' syntax as the CLI.
        """
        text = (text or "").strip()
        if not text:
            return None

        if text.startswith("!"):
            silent = text.startswith("!!")
            cmd = (text[2:] if silent else text[1:]).strip()
            output = core.run_shell(cmd)
            if silent:
                return f"$ {cmd}\n{output}"
            recorded = output
            if len(recorded) > core.SHELL_CONTEXT_LIMIT:
                recorded = recorded[: core.SHELL_CONTEXT_LIMIT] + "\n[...output truncated]"
            self.messages.append({"role": "user", "content": f"[shell] $ {cmd}\n{recorded}"})
            self._save()
            return None

        if text.startswith("/skill"):
            expanded, note = self._handle_skill_command(text)
            if expanded is None:
                return note
            text = expanded

        self.messages.append({"role": "user", "content": text})
        self.busy = True
        self.last_error = None
        self._save()
        return None

    # --- agent loop ---------------------------------------------------------

    @staticmethod
    def _to_tool_calls(raw) -> list[ToolCall]:
        calls = []
        for tc in raw:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], args=args))
        return calls

    def step(self) -> dict | None:
        """Run exactly one model call. The frontend calls this until it settles."""
        if not self.busy or self.pending:
            return None

        result = core.send_chat_request(
            self.provider,
            self.model,
            self.messages,
            tools=TOOLS if self.tools_enabled else None,
        )

        if "error" in result:
            self.busy = False
            self.last_error = result["error"]
            self._save()
            return {"type": "error", "error": result["error"]}

        msg = result["message"]

        if msg.get("tool_calls"):
            self.messages.append(msg)
            self.pending = self._to_tool_calls(msg["tool_calls"])
            self._save()
            return {"type": "tools", "calls": self.pending}

        self.messages.append({"role": "assistant", "content": msg.get("content") or ""})
        self.busy = False
        self._save()
        return {"type": "message", "content": msg.get("content") or ""}

    def approve_tools(self) -> list[dict]:
        """Execute every pending call and feed the results back."""
        results = []
        for call in self.pending:
            output = execute_tool(call.name, call.args)
            results.append({"name": call.name, "output": output})
            self.messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.name,
                "content": output,
            })
        self.pending = []
        self.busy = True
        self._save()
        return results

    def deny_tools(self) -> None:
        """Forget the request entirely and tell the model it was refused."""
        if self.messages and self.messages[-1].get("role") == "assistant":
            self.messages.pop()
        self.pending = []
        self.messages.append({
            "role": "user",
            "content": "[system] The user denied that tool call. Do not retry it. "
                       "Continue without it or ask for what you need.",
        })
        self.busy = True
        self._save()

    def send_tool_feedback(self, feedback: str) -> None:
        """Drop the request and replace it with a correction from the user."""
        if self.messages and self.messages[-1].get("role") == "assistant":
            self.messages.pop()
        self.pending = []
        self.messages.append({
            "role": "user",
            "content": f"[system] The user rejected that tool call with this feedback: {feedback}",
        })
        self.busy = True
        self._save()
