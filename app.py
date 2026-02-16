import streamlit as st
import os
import time
from pathlib import Path
from google import genai
from google.genai import types

# --- PAGE CONFIG ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- THEME CSS ---
st.markdown("""
<style>
.stApp {
  background:
    radial-gradient(800px circle at 50% 0%,
      rgba(0, 212, 255, 0.08),
      rgba(0, 212, 255, 0.00) 60%),
    var(--background-color);
  color: var(--text-color);
}
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 48px;
  font-weight: 1200;
  letter-spacing: -3px;
  margin-bottom: 0px;
  text-shadow:
    0 0 6px rgba(0, 212, 255, 0.55),
    0 0 18px rgba(0, 212, 255, 0.35),
    0 0 42px rgba(0, 212, 255, 0.20);
  animation: helix-glow 2.2s ease-in-out infinite;
}
@keyframes helix-glow {
  0%, 100% {
    text-shadow:
      0 0 6px rgba(0, 212, 255, 0.45),
      0 0 18px rgba(0, 212, 255, 0.28),
      0 0 42px rgba(0, 212, 255, 0.16);
  }
  50% {
    text-shadow:
      0 0 8px rgba(0, 212, 255, 0.75),
      0 0 24px rgba(0, 212, 255, 0.45),
      0 0 54px rgba(0, 212, 255, 0.24);
  }
}
.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.60;
  font-size: 18px;
  margin-bottom: 30px;
}
.thinking-container {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background-color: var(--secondary-background-color);
  border-radius: 8px;
  margin: 10px 0;
  border-left: 3px solid #fc8404;
}
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background-color: #fc8404;
  animation: thinking-pulse 1.4s ease-in-out infinite;
}
.thinking-dot:nth-child(1){ animation-delay: 0s; }
.thinking-dot:nth-child(2){ animation-delay: 0.2s; }
.thinking-dot:nth-child(3){ animation-delay: 0.4s; }
@keyframes thinking-pulse {
  0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
  30% { opacity: 1; transform: scale(1.2); }
}
</style>

<div class="big-title">📚 helix.ai</div>
<div class="subtitle">Your CIE Tutor for Grade 6-8!</div>
""", unsafe_allow_html=True)

# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: GOOGLE_API_KEY not found in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- CONFIG ---
MODEL_TEXT = "gemini-2.5-flash"
MODEL_IMAGE = "gemini-3-pro-image-preview"
CACHE_TTL = "3600s"          # 1 hour
MAX_TURNS = 7
SUMMARY_TRIGGER_MSGS = 22
THINK_STEP_SECONDS = 3
ENABLE_GOOGLE_SEARCH_TOOL = True

# Put your PDFs in repo root OR in ./books
BOOK_DIRS = [Path("."), Path("./books")]

PDF_FILENAMES = [
    "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
    "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
    "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
    "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
    "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
]

# --- SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
PUT YOUR FULL SYSTEM INSTRUCTION HERE (exactly as you wrote it)
"""

# --- UI helper ---
def show_thinking_animation(message="Helix is thinking"):
    thinking_html = f"""
    <div class="thinking-container">
        <span class="thinking-text">{message}</span>
        <div class="thinking-dots">
            <div class="thinking-dot"></div>
            <div class="thinking-dot"></div>
            <div class="thinking-dot"></div>
        </div>
    </div>
    """
    return st.markdown(thinking_html, unsafe_allow_html=True)

# --- Memory helpers ---
def build_history_contents(messages, max_turns=MAX_TURNS):
    text_msgs = [m for m in messages if (not m.get("is_image")) and m.get("role") in ("user", "assistant")]
    window = text_msgs[-(2 * max_turns):]
    contents = []
    for m in window:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return contents

def maybe_summarize_old_chat(messages, keep_last_msgs=SUMMARY_TRIGGER_MSGS):
    if len(messages) <= keep_last_msgs:
        return

    old = [m for m in messages[:-keep_last_msgs] if (not m.get("is_image")) and m.get("role") in ("user", "assistant")]
    if not old:
        return

    old_text = "\n".join([f'{m["role"].upper()}: {m["content"]}' for m in old])[-12000:]
    prompt = (
        "Summarize the conversation so far in <= 10 bullet points.\n"
        "Keep: grade/stage, subjects, chapters, constraints, decisions.\n"
        "Do NOT add new facts.\n\n"
        f"{old_text}"
    )

    resp = client.models.generate_content(
        model=MODEL_TEXT,
        contents=[prompt],
        config=types.GenerateContentConfig(system_instruction="You are a precise summarizer.")
    )
    st.session_state.chat_summary = (resp.text or "").strip()

# --- File path resolve ---
def resolve_pdf_paths():
    found = []
    missing = []
    for fn in PDF_FILENAMES:
        p = None
        for d in BOOK_DIRS:
            cand = d / fn
            if cand.exists():
                p = cand
                break
        if p:
            found.append(p)
        else:
            missing.append(fn)
    return found, missing

# --- Upload PDFs to Gemini Files API (once per session) ---
def upload_pdfs_to_gemini(pdf_paths):
    uploaded_names = []
    for p in pdf_paths:
        try:
            f = client.files.upload(file=str(p))
            while f.state.name == "PROCESSING":
                time.sleep(1)
                f = client.files.get(name=f.name)
            uploaded_names.append(f.name)  # store stable name, not the whole object
        except Exception as e:
            st.sidebar.error(f"Upload failed {p.name}: {e}")
    return uploaded_names

def get_uploaded_files(file_names):
    files = []
    for name in file_names:
        try:
            files.append(client.files.get(name=name))
        except Exception:
            pass
    return files

def chunk_list(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

# --- Explicit cache of ALL PDFs ---
def ensure_textbook_cache(uploaded_file_names):
    """
    Creates or reuses an explicit cache containing ALL PDFs + system instruction.
    Stores cache name in session_state.textbook_cache_name.
    """
    if not uploaded_file_names:
        st.error("No PDFs were uploaded to Gemini (uploaded_file_names is empty). Check your PDF paths on Streamlit Cloud.")
        st.stop()

    # Reuse cache if still valid
    cache_name = st.session_state.get("textbook_cache_name", "")
    if cache_name:
        try:
            _ = client.caches.get(name=cache_name)
            return cache_name
        except Exception:
            st.session_state.textbook_cache_name = ""

    # Build cache contents using Part.from_uri (SDK docs show this pattern for PDF caching)
    uploaded_files = get_uploaded_files(uploaded_file_names)
    if not uploaded_files:
        st.error("Could not re-fetch uploaded PDF handles from Gemini. Try clearing session / rebuilding.")
        st.stop()

    parts = [types.Part.from_uri(file_uri=f.uri, mime_type="application/pdf") for f in uploaded_files]

    # Avoid one mega-Content with too many parts; chunk into multiple contents
    contents = []
    for part_chunk in chunk_list(parts, 20):
        contents.append(types.Content(role="user", parts=part_chunk))

    cache = client.caches.create(
        model=MODEL_TEXT,
        config=types.CreateCachedContentConfig(
            display_name="helix-all-pdfs",
            system_instruction=SYSTEM_INSTRUCTION,
            contents=contents,
            ttl=CACHE_TTL,
        )
    )

    st.session_state.textbook_cache_name = cache.name
    return cache.name

# --- Sidebar debug controls ---
with st.sidebar:
    st.subheader("Debug")
    if st.button("Rebuild cache"):
        st.session_state.textbook_cache_name = ""
        st.rerun()

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant",
         "content": "👋 **Hey there! I'm Helix!**\n\nWhat are we learning today?"}
    ]

if "chat_summary" not in st.session_state:
    st.session_state.chat_summary = ""

if "uploaded_pdf_file_names" not in st.session_state:
    pdf_paths, missing = resolve_pdf_paths()

    with st.sidebar:
        st.caption(f"Found PDFs: {len(pdf_paths)} / {len(PDF_FILENAMES)}")
        if missing:
            st.warning("Missing PDFs:\n" + "\n".join(missing))

    if not pdf_paths:
        st.error("No PDFs found on disk. Put them in repo root or ./books with the exact filenames.")
        st.stop()

    with st.spinner("Uploading PDFs to Gemini (one-time per session)..."):
        st.session_state.uploaded_pdf_file_names = upload_pdfs_to_gemini(pdf_paths)

if "textbook_cache_name" not in st.session_state:
    st.session_state.textbook_cache_name = ""

if not st.session_state.textbook_cache_name:
    with st.spinner("Building explicit context cache (one-time per session)..."):
        ensure_textbook_cache(st.session_state.uploaded_pdf_file_names)

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask Helix a question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()

        try:
            with thinking_placeholder:
                show_thinking_animation("🔍 Helix is checking ALL textbooks 📚")
            time.sleep(THINK_STEP_SECONDS)

            with thinking_placeholder:
                show_thinking_animation("🧾 Helix is confirming sources…")
            time.sleep(THINK_STEP_SECONDS)

            with thinking_placeholder:
                show_thinking_animation("🧠 Helix is connecting ideas…")
            time.sleep(THINK_STEP_SECONDS)

            with thinking_placeholder:
                show_thinking_animation("✍️ Helix is forming your answer…")

            # rolling memory
            maybe_summarize_old_chat(st.session_state.messages, keep_last_msgs=SUMMARY_TRIGGER_MSGS)
            history_contents = build_history_contents(st.session_state.messages, max_turns=MAX_TURNS)

            request_contents = []
            if st.session_state.chat_summary.strip():
                request_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Conversation summary:\n" + st.session_state.chat_summary.strip())],
                    )
                )
            request_contents.extend(history_contents)

            cache_name = ensure_textbook_cache(st.session_state.uploaded_pdf_file_names)

            tools = [{"google_search": {}}] if ENABLE_GOOGLE_SEARCH_TOOL else None

            text_response = client.models.generate_content(
                model=MODEL_TEXT,
                contents=request_contents,
                config=types.GenerateContentConfig(
                    cached_content=cache_name,
                    tools=tools,
                ),
            )

            bot_text = text_response.text or ""

            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # Cache-hit debug (optional)
            try:
                cc = getattr(text_response.usage_metadata, "cached_content_token_count", None)
                if cc is not None:
                    st.sidebar.caption(f"cached_content_token_count: {cc}")
            except Exception:
                pass

            # --- IMAGE GENERATION ---
            if "IMAGE_GEN:" in bot_text:
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\\n")[0]

                img_status = st.empty()
                with img_status:
                    show_thinking_animation("🖌️ Helix is painting a diagram 🎨")

                for attempt in range(2):
                    try:
                        image_response = client.models.generate_content(
                            model=MODEL_IMAGE,
                            contents=[img_desc],
                            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
                        )
                        for part in image_response.parts:
                            if part.inline_data:
                                img_bytes = part.inline_data.data
                                img_status.empty()
                                st.image(img_bytes, caption="Generated by Helix")
                                st.session_state.messages.append(
                                    {"role": "assistant", "content": img_bytes, "is_image": True}
                                )
                        break
                    except Exception as inner_e:
                        if "503" in str(inner_e) and attempt == 0:
                            time.sleep(2)
                            continue
                        img_status.empty()
                        st.error(f"Image generation failed: {inner_e}")

        except Exception as e:
            thinking_placeholder.empty()
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Helix's connection timed out. Please refresh the page!")
                st.session_state.textbook_cache_name = ""
            else:
                st.error(f"Helix encountered a technical glitch: {e}")
