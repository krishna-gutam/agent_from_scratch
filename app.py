"""
app.py
------
The Streamlit frontend. It renders widgets and calls into
`backend.ChatSession`; it holds no agent logic of its own, so swapping it for
a TUI means rewriting this file only.

Run it with:  streamlit run app.py

The CLI (`python main.py`) still works untouched — this is a second frontend
over the same core, not a replacement.
"""

import json
import os

import streamlit as st

import backend
from backend import ChatSession, sanitize_content


# --- SESSION WIRING ---------------------------------------------------------


def get_session() -> ChatSession:
    """One ChatSession per browser session, kept across reruns."""
    if "session" not in st.session_state:
        st.session_state.session = ChatSession()
    return st.session_state.session


def flash(note: str | None) -> None:
    if note:
        st.session_state.flash = note


# --- SIDEBAR ----------------------------------------------------------------


def render_model_picker(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**🧠 Model**")

        if st.button("🔄 Re-discover models", use_container_width=True):
            with st.spinner("Querying every provider with a key set..."):
                backend.refresh_catalog()
            st.rerun()

        query = st.text_input("Search models", placeholder="gpt, llama, gemini…")
        matches = backend.search_catalog(query)

        if not matches:
            st.warning("No models found. Check your .env keys, then re-discover.")
            return

        shown = matches[:50]
        current = (session.provider, session.model)
        index = shown.index(current) if current in shown else 0

        picked = st.selectbox(
            f"{len(matches)} match(es)",
            shown,
            index=index,
            format_func=lambda pair: f"[{pair[0]}] {pair[1]}",
        )

        if picked != current:
            session.set_model(*picked)
            st.rerun()

        if session.provider and not backend.provider_ready(session.provider):
            env = backend.core.CONFIGS[session.provider]["api_key_env"]
            st.error(f"{env} is not set.")


def render_skills_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**🧩 Skills**")

        catalog = session.skill_catalog()
        if not catalog:
            st.caption("No skills found. Add one at `skills/<name>/SKILL.md`.")
            if st.button("🔄 Rescan skills", use_container_width=True):
                session.reload_skills()
                st.rerun()
            return

        names = [s["name"] for s in catalog]
        chosen = st.selectbox("Skill", names, key="skill_picker")
        description = next(s["description"] for s in catalog if s["name"] == chosen)
        if description:
            st.caption(description)

        task = st.text_area(
            "Task (optional)",
            height=80,
            placeholder="e.g. review backend.py",
            key="skill_task",
        )

        col1, col2 = st.columns([0.75, 0.25])
        if col1.button("▶️ Load skill", use_container_width=True, type="primary"):
            expanded = session.expand_skill(chosen, task)
            if expanded:
                session.submit(expanded)
                st.rerun()
        if col2.button("🔄", use_container_width=True, help="Rescan skills directory"):
            session.reload_skills()
            st.rerun()


def render_sidebar(session: ChatSession) -> bool:
    """Draw the sidebar. Returns whether tools should be auto-approved."""
    with st.sidebar:
        with st.container(border=True):
            threads = session.list_threads()
            index = threads.index(session.thread_id)

            selected = st.selectbox("Switch Conversation", threads, index=index)
            if selected != session.thread_id:
                session.switch_thread(selected)
                st.rerun()

            if st.button("➕ New Conversation", key="new_conv_btn", use_container_width=True):
                st.session_state.show_new_thread_input = True

            if st.session_state.get("show_new_thread_input", False):
                custom_id = st.text_input("Thread ID:", key="custom_thread_id_input")
                col1, col2 = st.columns(2)
                if col1.button("Create"):
                    st.session_state.show_new_thread_input = False
                    session.new_thread(custom_id or None)
                    st.rerun()
                if col2.button("Cancel"):
                    st.session_state.show_new_thread_input = False
                    st.rerun()

        render_model_picker(session)
        render_skills_panel(session)

        with st.container(border=True):
            st.metric(label="Conversation Tokens (est.)", value=session.token_count)

            session.tools_enabled = st.checkbox("Enable Tools", value=session.tools_enabled)
            auto_approve = st.checkbox("Auto-Approve Tools", value=False)

            if st.button("⏮️ Undo First Turn", use_container_width=True):
                if session.undo_first_turn():
                    st.rerun()

            if st.button("↩️ Undo Last Turn", use_container_width=True):
                if session.undo_last_turn():
                    st.rerun()

            if st.button("🗑️ Clear Chat History", use_container_width=True):
                session.clear_history()
                st.rerun()

        with st.container(border=True):
            st.markdown("**🖥️ Shell**")
            st.caption(f"cwd `{os.getcwd()}`")
            command = st.text_input("Command", key="shell_cmd", placeholder="git status")
            col1, col2 = st.columns(2)
            if col1.button("Run + share", use_container_width=True,
                           help="Output goes into the conversation"):
                if command.strip():
                    session.submit(f"!{command}")
                    st.rerun()
            if col2.button("Run quietly", use_container_width=True,
                           help="Output stays out of the conversation"):
                if command.strip():
                    flash(session.submit(f"!!{command}"))
                    st.rerun()

    return auto_approve


# --- TABS -------------------------------------------------------------------


def render_history_tab(session: ChatSession) -> None:
    st.subheader("Conversation Threads")

    for tid in session.list_threads():
        col1, col2 = st.columns([0.9, 0.1])
        summary = session.thread_summary(tid)

        with col1:
            with st.expander(f"Thread: {tid}  ({summary['count']} messages)"):
                st.write(f"**Last Human:** {summary['last_human'] or 'No human message'}")
                st.write(f"**Last AI:** {summary['last_ai'] or 'No AI message'}")

        with col2:
            if st.button("🗑️", key=f"del_thread_{tid}"):
                session.delete_thread(tid)
                st.rerun()


def render_logs_tab(session: ChatSession) -> None:
    st.subheader("Full Message History")

    for i, msg in enumerate(session.messages):
        col1, col2 = st.columns([0.9, 0.1])
        with col1:
            label = f"{i}: {msg.get('role')}"
            if msg.get("tool_calls"):
                label += f" ({', '.join(c['function']['name'] for c in msg['tool_calls'])})"
            with st.expander(label):
                st.code(json.dumps(msg, indent=2, default=str), language="json")
        with col2:
            if st.button("🗑️", key=f"del_msg_{i}"):
                session.delete_message(i)
                st.rerun()


def render_skills_tab(session: ChatSession) -> None:
    st.subheader("Installed Skills")

    catalog = session.skill_catalog()
    if not catalog:
        st.info("Nothing in `skills/` yet. Add `skills/<name>/SKILL.md` and rescan.")
        return

    for skill in catalog:
        with st.expander(f"{skill['name']} — {skill['description'] or 'no description'}"):
            st.caption(skill["path"])
            if skill["files"]:
                st.caption("Bundled: " + ", ".join(skill["files"]))
            st.code(skill["body"], language="markdown")


# --- CHAT -------------------------------------------------------------------


def render_transcript(session: ChatSession) -> None:
    """Chat history, rendered straight from the raw message list."""
    for msg in session.messages:
        role = msg.get("role")

        if role == "user":
            with st.chat_message("user"):
                st.markdown(sanitize_content(msg.get("content", "")))

        elif role == "assistant":
            content = sanitize_content(msg.get("content") or "")
            # Only render if there is actual text (ignores silent tool calls)
            if content.strip():
                with st.chat_message("assistant"):
                    st.markdown(content)
            elif msg.get("tool_calls"):
                with st.chat_message("assistant"):
                    names = ", ".join(c["function"]["name"] for c in msg["tool_calls"])
                    st.caption(f"🔧 requested: {names}")

        elif role == "tool":
            with st.chat_message("tool", avatar="🔧"):
                with st.expander(f"Result from {msg.get('name') or 'tool'}", expanded=False):
                    st.code(msg.get("content", ""), language="markdown")


def render_tool_approval(session: ChatSession, auto_approve: bool) -> None:
    """The approval gate shown whenever the model asked for a tool."""
    with st.chat_message("assistant"):
        st.warning("⚠️ **The agent has requested to execute the following tool(s):**")

        for call in session.pending:
            with st.expander(f"Tool Call: {call.name}", expanded=True):
                for key, value in call.display_args.items():
                    st.markdown(f"**{key}:**")
                    st.code(str(value), language="python")

        if auto_approve:
            st.info("Auto-approving because the checkbox is ticked...")
            session.approve_tools()
            st.rerun()

        col1, col2, col3 = st.columns([0.4, 0.3, 0.3])

        if col1.button("✅ Approve Action"):
            with st.status("Executing tools...", expanded=True) as status:
                for result in session.approve_tools():
                    st.write(f"**{result['name']}** → {result['output'][:200]}")
                status.update(label="Action complete!", state="complete", expanded=False)
            st.rerun()

        if col2.button("❌ Deny Action"):
            session.deny_tools()
            st.rerun()

        with col3:
            with st.popover("💬 Provide Feedback"):
                feedback = st.text_area("Tell the agent what to change:")
                if st.button("Submit Feedback"):
                    if feedback.strip():
                        session.send_tool_feedback(feedback)
                        st.rerun()
                    else:
                        st.warning("Please enter some feedback.")


# --- ENTRY POINT ------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="AI Model Chat", page_icon="💬", layout="wide")

    session = get_session()
    auto_approve = render_sidebar(session)

    tab_chat, tab_skills, tab_logs, tab_history = st.tabs(
        ["💬 Chat Interface", "🧩 Skills", "📜 Message Logs", "🕒 Manage History"]
    )

    with tab_history:
        render_history_tab(session)

    with tab_logs:
        render_logs_tab(session)

    with tab_skills:
        render_skills_tab(session)

    with tab_chat:
        if session.provider:
            st.caption(f"**Model:** `[{session.provider}] {session.model}`")

        note = st.session_state.pop("flash", None)
        if note:
            st.code(note, language="bash")

        render_transcript(session)

        if session.last_error:
            st.error(session.last_error)

        if session.pending:
            render_tool_approval(session, auto_approve)

        # One model call per rerun; the loop settles when `busy` goes false.
        elif session.busy:
            with st.chat_message("assistant"):
                with st.spinner(f"{session.model} is thinking..."):
                    session.step()
            st.rerun()

    # --- NEW USER INPUT ---

    if not session.is_ready():
        with tab_chat:
            st.warning(
                "⚠️ **Pick a model in the sidebar** and make sure its API key is set in your .env."
            )
        st.chat_input("Select a model to start chatting...", disabled=True)
        return

    prompt = st.chat_input("Message, !shell command, or /skill <name> …")

    if prompt:
        flash(session.submit(prompt))
        st.rerun()


if __name__ == "__main__":
    main()
