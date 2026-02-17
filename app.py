import streamlit as st
import time
from pathlib import Path
from google import genai
from google.genai import types

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

MODEL_TEXT = "gemini-2.5-flash"
MODEL_IMAGE = "gemini-3-pro-image-preview"

MAX_TURNS = 7
SUMMARY_TRIGGER_MSGS = 22
THINK_STEP_SECONDS = 2

# Upload retry/backoff (helps Streamlit Cloud)
UPLOAD_RETRIES = 4
UPLOAD_BASE_SLEEP = 1.5
UPLOAD_BETWEEN_FILES = 0.3

# Cache TTL on Google side (CachedContent)
CACHE_TTL = "21600s"  # 6 hours
CACHE_CHUNK_PARTS = 20  # parts per Content chunk

# Put your full system instruction here
SYSTEM_INSTRUCTION = """PASTE YOUR FULL SYSTEM INSTRUCTION HERE"""

# =========================
# UI (optional styling)
# =========================
st.markdown("""
<style>
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 44px;
  font-weight: 900;
  letter-spacing: -2px;
  margin-bottom: 0px;
}
.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.65;
  font-size: 16px;
  margin-bottom: 18px;
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
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 700; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background-color: #fc8404;
  animation: thinking-pulse 1.4s ease-in-out infinite;
}
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

def thinking(message: str):
    html = f"""
    <div class="thinking-container">
      <span class="thinking-text">{message}</span>
      <div class="thinking-dots">
        <div class="thinking-dot"></div>
        <div class="thinking-dot"></div>
        <div class="thinking-dot"></div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# =========================
# API
# =========================
api_key = (st.secrets.get("GOOGLE_API_KEY", "") or "").strip()
if not api_key:
    st.error("Missing GOOGLE_API_KEY in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# =========================
# Helpers: secrets parsing
# =========================
def get_secret_str(key: str) -> str:
    return (st.secrets.get(key, "") or "").strip()

def parse_csv_secret(key: str) -> list[str]:
    raw = get_secret_str(key)
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]

# =========================
# Helpers: chat memory
# =========================
def build_history_contents(messages, max_turns=MAX_TURNS):
    text_msgs = [m for m in messages if m.get("role") in ("user", "assistant") and not m.get("is_image")]
    window = text_msgs[-(2 * max_turns):]
    contents = []
    for m in window:
        role = "user" if m["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return contents

def maybe_summarize_old_chat(messages, keep_last_msgs=SUMMARY_TRIGGER_MSGS):
    if len(messages) <= keep_last_msgs:
        return

    old = [m for m in messages[:-keep_last_msgs] if m.get("role") in ("user", "assistant") and not m.get("is_image")]
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

# =========================
# Helpers: PDF discovery
# =========================
BASE_DIR = Path(__file__).resolve().parent

def find_repo_pdfs() -> list[Path]:
    bad_fragments = ("/.git/", "/__pycache__/", "/.venv/", "/venv/", "/site-packages/")
    pdfs = []
    for p in BASE_DIR.rglob("*.pdf"):
        s = str(p)
        if p.is_file() and not any(b in s for b in bad_fragments):
            pdfs.append(p)
    return sorted(pdfs)

# =========================
# Helpers: Gemini Files upload (Google-side)
# =========================
def upload_one_pdf(path: Path):
    last_err = None
    for attempt in range(UPLOAD_RETRIES):
        try:
            if attempt > 0:
                time.sleep(UPLOAD_BASE_SLEEP * (2 ** (attempt - 1)))

            f = client.files.upload(file=str(path), config={"mime_type": "application/pdf"})
            while f.state.name == "PROCESSING":
                time.sleep(1)
                f = client.files.get(name=f.name)
            return f, None
        except Exception as e:
            last_err = e
    return None, last_err

def upload_all_pdfs(pdf_paths: list[Path]):
    uploaded = []
    failures = []
    prog = st.sidebar.progress(0)
    total = max(1, len(pdf_paths))

    for i, p in enumerate(pdf_paths, start=1):
        f, err = upload_one_pdf(p)
        if f:
            uploaded.append(f)
        else:
            failures.append((p.name, f"{type(err).__name__}: {err}"))
        prog.progress(i / total)
        time.sleep(UPLOAD_BETWEEN_FILES)

    return uploaded, failures

def files_from_secret_names(file_names: list[str]):
    files = []
    errors = []
    for n in file_names:
        try:
            files.append(client.files.get(name=n))
        except Exception as e:
            errors.append((n, f"{type(e).__name__}: {e}"))
    return files, errors

# =========================
# Helpers: CachedContent (Google-side)
# =========================
def chunk_list(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

def create_cache_from_files(uploaded_files):
    # Build cache contents from file URIs
    parts = [types.Part.from_uri(file_uri=f.uri, mime_type="application/pdf") for f in uploaded_files]
    contents = [types.Content(role="user", parts=chunk) for chunk in chunk_list(parts, CACHE_CHUNK_PARTS)]

    cache = client.caches.create(
        model=MODEL_TEXT,
        config=types.CreateCachedContentConfig(
            display_name="helix-all-pdfs",
            system_instruction=SYSTEM_INSTRUCTION,
            contents=contents,
            ttl=CACHE_TTL,
        ),
    )
    return cache

def get_or_create_cache(uploaded_files):
    secret_cache_name = get_secret_str("GEMINI_CACHE_NAME")
    if secret_cache_name:
        try:
            cache_obj = client.caches.get(name=secret_cache_name)
            return cache_obj.name, "reused"
        except Exception:
            pass

    cache = create_cache_from_files(uploaded_files)
    return cache.name, "created"

# =========================
# Sidebar: Admin workflow
# =========================
with st.sidebar:
    st.subheader("Setup")
    admin_mode = st.checkbox("Admin mode (upload PDFs + create cache)", value=False)
    st.caption("If secrets already exist, keep Admin mode OFF for fast start.")

    st.write("Secrets present?")
    st.write("GEMINI_PDF_FILE_NAMES:", "YES" if bool(get_secret_str("GEMINI_PDF_FILE_NAMES")) else "NO")
    st.write("GEMINI_CACHE_NAME:", "YES" if bool(get_secret_str("GEMINI_CACHE_NAME")) else "NO")

# =========================
# Load or build Google assets
# =========================
def ensure_google_ready():
    # Try to reuse Google IDs from secrets (fast path)
    secret_file_names = parse_csv_secret("GEMINI_PDF_FILE_NAMES")
    if secret_file_names:
        files, errs = files_from_secret_names(secret_file_names)
        with st.sidebar:
            st.write("Google files loaded:", len(files))
            if errs:
                st.warning("Some Google file IDs failed (expired/invalid).")
                for n, e in errs[:6]:
                    st.write("-", n, "=>", e)

        if files:
            cache_name, mode = get_or_create_cache(files)
            with st.sidebar:
                st.write("Cache:", cache_name, f"({mode})")
            st.session_state.google_files = files
            st.session_state.google_cache_name = cache_name
            return True

    # No valid secrets => require admin once
    if not admin_mode:
        st.warning("Missing/expired Google file IDs. Turn ON Admin mode once, upload, then paste printed secrets.")
        return False

    pdf_paths = find_repo_pdfs()
    with st.sidebar:
        st.write("Repo PDFs found:", len(pdf_paths))
        for p in pdf_paths[:8]:
            st.write("•", str(p.relative_to(BASE_DIR)))

    if not pdf_paths:
        st.error("No PDFs found in the deployed filesystem.")
        return False

    run = st.sidebar.button("ADMIN: Upload PDFs + Create Cache now")
    if not run:
        return False

    with st.spinner("Uploading PDFs to Gemini Files API (Google-side)..."):
        uploaded_files, failures = upload_all_pdfs(pdf_paths)

    with st.sidebar:
        st.write("Uploaded OK:", len(uploaded_files))
        if failures:
            st.error(f"Upload failures: {len(failures)}")
            for name, err in failures[:10]:
                st.write("-", name, "=>", err)

    if not uploaded_files:
        st.error("0 PDFs uploaded. Fix upload failures above.")
        return False

    with st.spinner("Creating CachedContent (Google-side cache)..."):
        cache_name, mode = get_or_create_cache(uploaded_files)

    # Print secrets values for you to paste
    file_names_csv = ",".join([f.name for f in uploaded_files])
    with st.sidebar:
        st.success("Copy/paste into Streamlit Secrets:")
        st.code(f'GEMINI_PDF_FILE_NAMES = "{file_names_csv}"', language="text")
        st.code(f'GEMINI_CACHE_NAME = "{cache_name}"', language="text")
        st.caption("Then restart app with Admin mode OFF.")

    st.session_state.google_files = uploaded_files
    st.session_state.google_cache_name = cache_name
    return True

assets_ready = ensure_google_ready()

# =========================
# Init chat session
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "What are we learning today?"}]
if "chat_summary" not in st.session_state:
    st.session_state.chat_summary = ""

# Show chat so far
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        if m.get("is_image"):
            st.image(m["content"])
        else:
            st.markdown(m["content"])

# =========================
# Chat loop (uses Google cache)
# =========================
prompt = st.chat_input("Ask Helix a question...")
if prompt:
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        if not assets_ready:
            st.error("Google cache/files not ready. Turn ON Admin mode once and run the upload+cache step.")
        else:
            placeholder = st.empty()
            with placeholder:
                thinking("🔍 Helix is checking ALL textbooks 📚")
            time.sleep(THINK_STEP_SECONDS)

            with placeholder:
                thinking("✍️ Helix is forming your answer…")

            maybe_summarize_old_chat(st.session_state.messages, keep_last_msgs=SUMMARY_TRIGGER_MSGS)
            history = build_history_contents(st.session_state.messages, max_turns=MAX_TURNS)

            req_contents = []
            if st.session_state.chat_summary.strip():
                req_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Conversation summary:\n" + st.session_state.chat_summary.strip())],
                    )
                )
            req_contents.extend(history)

            resp = client.models.generate_content(
                model=MODEL_TEXT,
                contents=req_contents,  # IMPORTANT: only prompt/history here, not PDFs
                config=types.GenerateContentConfig(
                    cached_content=st.session_state.google_cache_name,
                    tools=[{"google_search": {}}],
                ),
            )

            # Debug: see if cache hit tokens show up
            with st.sidebar:
                um = getattr(resp, "usage_metadata", None)
                st.write("RESPONSE usage_metadata:", um)
                st.write("cached_content_token_count:", getattr(um, "cached_content_token_count", None))

            answer = resp.text or ""
            placeholder.empty()
            st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
