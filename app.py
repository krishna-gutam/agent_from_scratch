"""
app.py
------
The Streamlit frontend. It renders widgets and calls into `backend.ChatSession`
and `workspace`; it holds no agent logic of its own, so swapping it for a TUI
means rewriting this file only.

Run it with:  streamlit run app.py

The CLI (`python main.py`) still works untouched — this is a second frontend
over the same core, not a replacement.
"""

import json
import os
import time
import uuid

import streamlit as st

import backend
import workspace
from backend import ChatSession, sanitize_content

try:                                   # pip install streamlit-ace for the real editor
    from streamlit_ace import st_ace
except ImportError:
    st_ace = None


# --- SESSION WIRING ---------------------------------------------------------


def get_session() -> ChatSession:
    """One ChatSession per workspace, kept across reruns."""
    session = st.session_state.get("session")
    if session is None or session.root != os.path.abspath(workspace.current()):
        session = ChatSession()
        st.session_state.session = session
    return session


def switch_workspace_environment(error: str | None = None) -> None:
    """Re-bind the session after chdir into another project."""
    if error:
        st.error(error)
        return
    # Drop the session and every workspace-scoped widget value; the next
    # get_session() rebuilds against the new cwd.
    for key in ("session", "edit_content", "edit_path", "editor_key", "flash"):
        st.session_state.pop(key, None)
    st.rerun()


def flash(note: str | None) -> None:
    if note:
        st.session_state.flash = note


# --- SIDEBAR ----------------------------------------------------------------


def render_workspace_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**📂 Workspace**")

        options = ["Current Directory"] + workspace.load_recent_projects()
        selected = st.selectbox(
            "Switch Workspace", options, format_func=lambda p: os.path.basename(p) or p
        )

        if st.button("➕ Create New Project", key="new_proj_btn", use_container_width=True):
            st.session_state.show_new_project_input = True

        if st.session_state.get("show_new_project_input", False):
            new_path = st.text_input(
                "Absolute path for the new project:", key="new_proj_path_input"
            )
            col1, col2 = st.columns(2)
            if col1.button("Create Project"):
                st.session_state.show_new_project_input = False
                switch_workspace_environment(workspace.create_project(new_path))
            if col2.button("Cancel Project"):
                st.session_state.show_new_project_input = False
                st.rerun()

        if selected != "Current Directory" and os.path.abspath(selected) != session.root:
            switch_workspace_environment(workspace.switch_to(selected))

        st.caption(f"**Active:** `{workspace.current()}`")
        if os.path.abspath(workspace.current()) not in [
            os.path.abspath(p) for p in workspace.load_recent_projects()
        ]:
            if st.button("📌 Remember this directory", use_container_width=True):
                workspace.save_recent_project(workspace.current())
                st.rerun()


def render_thread_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**💬 Conversation**")

        threads = session.list_threads()
        index = threads.index(session.thread_id)

        selected = st.selectbox(
            "Switch Conversation", threads, index=index, format_func=lambda t: t[:24]
        )
        if selected != session.thread_id:
            session.switch_thread(selected)
            st.rerun()

        if st.button("➕ New Conversation", key="new_conv_btn", use_container_width=True):
            st.session_state.show_new_thread_input = True

        if st.session_state.get("show_new_thread_input", False):
            custom_id = st.text_input("Thread ID (optional):", key="custom_thread_id_input")
            col1, col2 = st.columns(2)
            if col1.button("Create"):
                error = session.new_thread(custom_id or None)
                if error:
                    st.error(error)
                else:
                    st.session_state.show_new_thread_input = False
                    st.rerun()
            if col2.button("Cancel"):
                st.session_state.show_new_thread_input = False
                st.rerun()

        st.caption(f"{len(threads)} thread(s) in this workspace")


def render_active_model(session: ChatSession) -> None:
    """Read-only status block. Choosing a model happens in the Models tab."""
    with st.container(border=True):
        st.markdown("**🧠 Model**")
        if session.model:
            st.caption(f"`{session.model}`")
            st.caption(f"via {session.provider}")
            if not backend.provider_ready(session.provider):
                env = backend.core.CONFIGS[session.provider]["api_key_env"]
                st.error(f"{env} is not set.")
        else:
            st.caption("None selected — open the **🧠 Models** tab.")


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
            "Task (optional)", height=80, placeholder="e.g. review backend.py", key="skill_task"
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
        render_workspace_panel(session)
        render_thread_panel(session)
        render_active_model(session)
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

        with st.container(border=True):
            notes = st.text_area(
                "Quick Notes:", value=workspace.read_notes(), height=200, key="sidebar_notes"
            )
            if st.button("Save Quick Notes", use_container_width=True):
                result = workspace.write_notes(notes)
                st.error(result) if result.startswith("Error") else st.success(result)

    return auto_approve


# --- TABS -------------------------------------------------------------------


def render_history_tab(session: ChatSession) -> None:
    st.subheader("Conversation Threads")
    st.caption(f"Stored in `{workspace.chats_dir()}`")

    for tid in session.list_threads():
        summary = session.thread_summary(tid)
        col1, col2, col3, col4 = st.columns([0.7, 0.14, 0.08, 0.08])

        with col1:
            label = f"Thread: {tid}  ({summary['count']} messages)"
            if tid == session.thread_id:
                label = "▶ " + label
            with st.expander(label):
                st.write(f"**Last Human:** {summary['last_human'] or 'No human message'}")
                st.write(f"**Last AI:** {summary['last_ai'] or 'No AI message'}")

        with col2:
            new_id = st.text_input(
                "New ID", key=f"rename_input_{tid}", label_visibility="collapsed",
                placeholder="new id",
            )
        with col3:
            if st.button("R", key=f"rename_btn_{tid}", help="Rename"):
                error = session.rename_thread(tid, new_id)
                if error:
                    st.error(error)
                else:
                    st.rerun()
        with col4:
            if st.button("D", key=f"del_thread_{tid}", help="Delete"):
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


def render_editor_tab() -> None:
    st.subheader("File Editor")
    st.caption(f"Editing inside `{workspace.current()}`")

    files = workspace.list_project_files()
    if not files:
        st.info("No editable files found in this workspace.")
        return

    edit_path = st.selectbox("Select a file to edit:", files)

    if st.button("Load File"):
        content = workspace.read_file(edit_path)
        if content.startswith("Error"):
            st.error(content)
        else:
            st.session_state.edit_content = content
            st.session_state.edit_path = edit_path
            # A unique key forces the editor to remount with the new text
            st.session_state.editor_key = str(uuid.uuid4())

    if "edit_content" not in st.session_state:
        return

    loaded_path = st.session_state.get("edit_path", edit_path)
    if loaded_path != edit_path:
        st.warning(f"Editing `{loaded_path}`. Press Load File to open `{edit_path}`.")

    st.session_state.setdefault("editor_key", "editor_initial")
    language = workspace.language_for(loaded_path)

    if st_ace:
        new_content = st_ace(
            value=st.session_state.edit_content,
            language=language if language != "text" else "plain_text",
            theme="monokai",
            key=st.session_state.editor_key,
        )
    else:
        st.caption("`pip install streamlit-ace` for syntax highlighting.")
        new_content = st.text_area(
            "Contents", value=st.session_state.edit_content, height=520,
            key=st.session_state.editor_key,
        )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 Save Changes", use_container_width=True):
            result = workspace.write_file(loaded_path, new_content)
            if result.startswith("Error"):
                st.error(result)
            else:
                st.success(result)
                st.session_state.edit_content = new_content

    with col2:
        if st.button("🔄 Reset Unsaved Changes", use_container_width=True):
            st.session_state.edit_content = workspace.read_file(loaded_path)
            st.session_state.editor_key = str(uuid.uuid4())
            st.rerun()


def render_models_tab(session: ChatSession) -> None:
    st.subheader("Model Selection")

    # --- current model + catalog freshness ---
    col1, col2 = st.columns([0.65, 0.35])
    with col1:
        if session.model:
            st.success(f"**Active:** `{session.model}`  ·  {session.provider}")
        else:
            st.warning("No model selected yet. Pick one below.")
    with col2:
        if st.button("🔄 Re-discover models", use_container_width=True, type="primary"):
            with st.spinner("Querying every provider with a key set..."):
                backend.refresh_catalog()
            st.rerun()
        updated = backend.catalog_updated_at()
        st.caption(
            f"Catalog updated {time.strftime('%d %b %H:%M', time.localtime(updated))}"
            if updated else "Catalog has never been built."
        )

    # --- provider key status ---
    status = backend.provider_status()
    cols = st.columns(len(status))
    for col, entry in zip(cols, status):
        with col:
            if entry["ready"]:
                col.metric(entry["provider"], f"{entry['count']} models")
            else:
                col.metric(entry["provider"], "no key", delta=entry["env"], delta_color="off")

    if not any(entry["ready"] for entry in status):
        st.error("No API keys found. Set at least one in your .env, then re-discover.")
        return

    st.divider()

    # --- search + filter ---
    col1, col2 = st.columns([0.55, 0.45])
    query = col1.text_input("Search", placeholder="gpt, llama, gemini…", key="model_search")
    wanted = col2.multiselect(
        "Providers",
        [e["provider"] for e in status if e["count"]],
        default=[e["provider"] for e in status if e["count"]],
        key="model_provider_filter",
    )

    matches = [pair for pair in backend.search_catalog(query) if pair[0] in wanted]

    if not matches:
        st.info("Nothing matches that search.")
        return

    limit = 60
    st.caption(
        f"{len(matches)} model(s)" + (f" — showing the first {limit}" if len(matches) > limit else "")
    )

    # --- results ---
    current = (session.provider, session.model)
    for provider, model in matches[:limit]:
        is_current = (provider, model) == current
        col1, col2, col3 = st.columns([0.62, 0.22, 0.16])
        col1.markdown(f"{'✅ ' if is_current else ''}`{model}`")
        col2.caption(provider)
        if is_current:
            col3.button("In use", key=f"use_{provider}_{model}", disabled=True,
                        use_container_width=True)
        elif col3.button("Use", key=f"use_{provider}_{model}", use_container_width=True):
            session.set_model(provider, model)
            st.rerun()


def render_skills_tab(session: ChatSession) -> None:
    st.subheader("Installed Skills")

    catalog = session.skill_catalog()
    if not catalog:
        st.info("Nothing in `skills/` yet. Add `skills/<name>/SKILL.md` and rescan.")
        return

    st.caption("Skills live beside the app, so they follow you across workspaces.")
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

    tab_chat, tab_models, tab_edit, tab_skills, tab_logs, tab_history = st.tabs(
        [
            "💬 Chat Interface",
            "🧠 Models",
            "📝 Editor",
            "🧩 Skills",
            "📜 Message Logs",
            "🕒 Manage History",
        ]
    )

    with tab_models:
        render_models_tab(session)

    with tab_history:
        render_history_tab(session)

    with tab_logs:
        render_logs_tab(session)

    with tab_skills:
        render_skills_tab(session)

    with tab_edit:
        render_editor_tab()

    with tab_chat:
        if session.provider:
            st.caption(
                f"**Model:** `[{session.provider}] {session.model}` · "
                f"**Thread:** `{session.thread_id}` · **Dir:** `{os.path.basename(session.root)}`"
            )

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
                "⚠️ **Open the 🧠 Models tab** to pick a model, and make sure its API key is "
                "set in your .env."
            )
        st.chat_input("Select a model to start chatting...", disabled=True)
        return

    prompt = st.chat_input("Message, !shell command, or /skill <name> …")

    if prompt:
        flash(session.submit(prompt))
        st.rerun()


if __name__ == "__main__":
    main()
