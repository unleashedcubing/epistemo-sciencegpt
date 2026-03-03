import streamlit as st
import os
import time
import re
import uuid
import concurrent.futures
from pathlib import Path
from io import BytesIO

from google import genai
from google.genai import types

# Firebase Firestore Imports
from google.cloud import firestore
from google.oauth2 import service_account

# ReportLab PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Image as RLImage, Table, TableStyle
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib import colors

# Matplotlib (Python-native charts)
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

# -----------------------------
# 1) SETUP & CONFIG
# -----------------------------
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

st.markdown("""
<style>
.stApp { background: radial-gradient(800px circle at 50% 0%, rgba(0, 212, 255, 0.08), rgba(0, 212, 255, 0.00) 60%), var(--background-color); color: var(--text-color); }
.big-title { font-family: 'Inter', sans-serif; color: #00d4ff; text-align: center; font-size: 48px; font-weight: 1200; letter-spacing: -3px; margin-bottom: 0px; text-shadow: 0 0 6px rgba(0, 212, 255, 0.55); }
.subtitle { text-align: center; opacity: 0.60; font-size: 18px; margin-bottom: 30px; }
.thinking-container { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background-color: var(--secondary-background-color); border-radius: 8px; margin: 10px 0; border-left: 3px solid #fc8404; }
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot { width: 6px; height: 6px; border-radius: 50%; background-color: #fc8404; animation: thinking-pulse 1.4s infinite; }
.thinking-dot:nth-child(2){ animation-delay: 0.2s; }
.thinking-dot:nth-child(3){ animation-delay: 0.4s; }
@keyframes thinking-pulse { 0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); } 30% { opacity: 1; transform: scale(1.2); } }
</style>
""", unsafe_allow_html=True)

# -----------------------------
# 2) GUEST MODE & NATIVE GOOGLE LOGIN
# -----------------------------
if hasattr(st, "user"):
    auth_object = st.user
elif hasattr(st, "experimental_user"):
    auth_object = st.experimental_user
else:
    st.error("Your Streamlit version is too old for Google Login.")
    st.stop()

is_authenticated = getattr(auth_object, "is_logged_in", False)

# Initialize Firestore Connection
@st.cache_resource
def get_firestore_client():
    if "firebase" in st.secrets:
        key_dict = dict(st.secrets["firebase"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds)
    return None

db = get_firestore_client()

# Firebase Threading Helper Functions
def get_threads_collection():
    if is_authenticated and hasattr(auth_object, "email") and db is not None:
        return db.collection("users").document(auth_object.email).collection("threads")
    return None

def get_all_threads():
    coll_ref = get_threads_collection()
    if coll_ref:
        try:
            docs = coll_ref.order_by("updated_at", direction=firestore.Query.DESCENDING).limit(15).stream()
            threads = []
            for doc in docs:
                data = doc.to_dict()
                threads.append({
                    "id": doc.id,
                    "title": data.get("title", "New Chat"),
                    "updated_at": data.get("updated_at", 0),
                    "metadata": data.get("metadata", {"subjects": [], "grades": []}),
                    "user_edited_title": data.get("user_edited_title", False),
                })
            return threads
        except Exception:
            pass
    return []

def get_default_greeting():
    return [{
        "role": "assistant",
        "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizzes!\nYou can also **attach photos, PDFs, or text files directly in the chat box below!** 📸📄\n\n**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\nWhat are we learning today?",
        "is_greeting": True,
    }]

def load_chat_history(thread_id):
    coll_ref = get_threads_collection()
    if coll_ref and thread_id:
        try:
            doc = coll_ref.document(thread_id).get()
            if doc.exists:
                return doc.to_dict().get("messages", [])
        except Exception:
            pass
    return get_default_greeting()

def save_chat_history():
    coll_ref = get_threads_collection()
    if not coll_ref:
        return  # Skip if Guest Mode

    current_id = st.session_state.current_thread_id
    safe_messages = []

    # Metadata Trackers
    detected_subjects = set()
    detected_grades = set()

    for msg in st.session_state.messages:
        content_str = str(msg.get("content", ""))
        role = msg.get("role")

        if role == "user":
            q = content_str.lower()
            if any(k in q for k in ["math", "algebra", "geometry", "calculate", "equation", "number", "fraction"]):
                detected_subjects.add("Math")
            if any(k in q for k in ["science", "cell", "biology", "physics", "chemistry", "experiment", "gravity"]):
                detected_subjects.add("Science")
            if any(k in q for k in ["english", "poem", "story", "essay", "writing", "grammar", "noun", "verb"]):
                detected_subjects.add("English")
            if any(k in q for k in ["stage 7", "grade 6", "year 7"]):
                detected_grades.add("Stage 7")
            if any(k in q for k in ["stage 8", "grade 7", "year 8"]):
                detected_grades.add("Stage 8")
            if any(k in q for k in ["stage 9", "grade 8", "year 9"]):
                detected_grades.add("Stage 9")

        safe_messages.append({
            "role": str(role),
            "content": content_str,
            "is_greeting": bool(msg.get("is_greeting", False)),
            "is_downloadable": bool(msg.get("is_downloadable", False)),
        })

    data = {
        "messages": safe_messages,
        "updated_at": time.time(),
        "metadata": {
            "subjects": list(detected_subjects),
            "grades": list(detected_grades),
        },
    }

    try:
        coll_ref.document(current_id).set(data, merge=True)
    except Exception as e:
        st.toast(f"⚠️ Database Error: Could not save chat - {e}")

# -----------------------------
# 2.5) AUTO-TITLE GENERATOR
# -----------------------------
def safe_response_text(resp) -> str:
    try:
        t = getattr(resp, "text", None)
        if t:
            return str(t)
    except Exception:
        pass
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            parts = getattr(content, "parts", None) or []
            texts = [getattr(p, "text", None) for p in parts if getattr(p, "text", None)]
            if texts:
                return "\n".join(texts)
    except Exception:
        pass
    return ""

def generate_chat_title(client, messages):
    try:
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return "New Chat"

        context_text = "\n".join(user_msgs[-3:])
        prompt = (
            "Summarize this conversation context into a very short, punchy chat title (maximum 4 words). "
            "Do not use quotes or punctuation. Context: "
            f"{context_text}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=15
            ),
        )

        title = safe_response_text(response).strip().replace('"', '').replace("'", "")
        return title if title else "New Chat"
    except Exception as e:
        print(f"Title Gen Error: {e}")
        return "New Chat"

# -----------------------------
# 3) INITIALIZE SESSION STATE
# -----------------------------
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = get_default_greeting()

if "delete_requested_for" not in st.session_state:
    st.session_state.delete_requested_for = None

# -----------------------------
# 3.5) DIALOG MENUS
# -----------------------------
@st.dialog("⚠️ Maximum Chats Reached")
def confirm_new_chat_dialog(oldest_thread_id):
    st.write("You have hit the maximum limit of **15 saved chats**.")
    st.write("If you create a new chat, your oldest chat will be permanently deleted.")
    st.write("Are you sure you want to do this?")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("Yes, Create New", type="primary", use_container_width=True):
            coll_ref = get_threads_collection()
            if coll_ref:
                try:
                    coll_ref.document(oldest_thread_id).delete()
                except Exception:
                    pass
            st.session_state.current_thread_id = str(uuid.uuid4())
            st.session_state.messages = get_default_greeting()
            st.rerun()

@st.dialog("🗑️ Delete Chat")
def confirm_delete_chat_dialog(thread_id_to_delete):
    st.write("Are you sure you want to permanently delete this chat?")
    st.write("*This action cannot be undone.*")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            st.session_state.delete_requested_for = None
            st.rerun()
    with col2:
        if st.button("Yes, Delete", type="primary", use_container_width=True):
            coll_ref = get_threads_collection()
            if coll_ref:
                try:
                    coll_ref.document(thread_id_to_delete).delete()
                except Exception:
                    pass

            if st.session_state.current_thread_id == thread_id_to_delete:
                st.session_state.current_thread_id = str(uuid.uuid4())
                st.session_state.messages = get_default_greeting()

            st.session_state.delete_requested_for = None
            st.rerun()

@st.dialog("⚙️ Chat Settings")
def chat_settings_dialog(thread_data):
    st.markdown("**Chat Metadata**")
    subs = ", ".join(thread_data.get("metadata", {}).get("subjects", [])) or "None"
    grds = ", ".join(thread_data.get("metadata", {}).get("grades", [])) or "None"
    st.caption(f"📚 **Subjects:** {subs}")
    st.caption(f"🎓 **Grades:** {grds}")

    st.divider()

    new_title = st.text_input("Rename Chat", value=thread_data["title"], key=f"ren_in_{thread_data['id']}")
    if st.button("💾 Save Name", key=f"ren_btn_{thread_data['id']}", use_container_width=True):
        coll_ref = get_threads_collection()
        if coll_ref:
            coll_ref.document(thread_data["id"]).set({
                "title": new_title,
                "user_edited_title": True
            }, merge=True)
        st.rerun()

    st.divider()

    if st.button("🗑️ Delete Chat", key=f"del_btn_set_{thread_data['id']}", type="primary", use_container_width=True):
        st.session_state.delete_requested_for = thread_data["id"]
        st.rerun()

# -----------------------------
# 4) SIDEBAR UI (MULTIPLE CHATS)
# -----------------------------
with st.sidebar:
    st.title("Account Settings")
    if not is_authenticated:
        st.markdown("👋 **You are chatting as a Guest!**\n\n*Log in with Google to save your chat history permanently!*")
        if st.button("Log in with Google", type="primary", use_container_width=True):
            st.login(provider="google")
    else:
        user_name = auth_object.get("name", "Student") if hasattr(auth_object, "get") else "Student"
        st.success(f"Welcome back, **{user_name}**! 📚")
        if st.button("Log out"):
            st.logout()

    st.divider()

    sidebar_threads = get_all_threads() if is_authenticated else []

    if st.button("➕ New Chat", use_container_width=True):
        if is_authenticated and len(sidebar_threads) >= 15:
            oldest_id = sidebar_threads[-1]["id"]
            confirm_new_chat_dialog(oldest_id)
        else:
            st.session_state.current_thread_id = str(uuid.uuid4())
            st.session_state.messages = get_default_greeting()
            st.rerun()

    if is_authenticated:
        st.subheader("Recent Chats")
        if not sidebar_threads:
            st.caption("*Your saved chats will appear here.*")

        for t in sidebar_threads:
            col1, col2 = st.columns([0.85, 0.15], vertical_alignment="center")

            with col1:
                icon = "🟢" if t["id"] == st.session_state.current_thread_id else "💬"
                if st.button(f"{icon} {t['title']}", key=f"btn_{t['id']}", use_container_width=True):
                    st.session_state.current_thread_id = t["id"]
                    st.session_state.messages = load_chat_history(t["id"])
                    st.rerun()

            with col2:
                if st.button("", icon=":material/more_vert:", key=f"set_btn_{t['id']}", use_container_width=True):
                    chat_settings_dialog(t)

if st.session_state.delete_requested_for:
    confirm_delete_chat_dialog(st.session_state.delete_requested_for)

# Main app title
st.markdown("<div class='big-title'>📚 helix.ai</div>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Your CIE Tutor for Grade 6-8!</div>", unsafe_allow_html=True)

# -----------------------------
# 5) INITIALIZE GEMINI
# -----------------------------
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("🚨 Critical Error: GOOGLE_API_KEY not found.")
        st.stop()

try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"🚨 Failed to initialize Gemini Client: {e}")
    st.stop()

# -----------------------------
# 6) HELPERS & LATEX CLEANER
# -----------------------------
def get_friendly_name(filename: str) -> str:
    if not filename:
        return "Cambridge Textbook"
    name = filename.replace(".pdf", "").replace(".PDF", "")
    parts = name.split("_")
    if len(parts) < 3 or parts[0] != "CIE":
        return filename
    grade = parts[1]
    book_type = "Workbook" if "WB" in parts else "Textbook"
    if "ANSWERS" in parts:
        book_type += " Answers"
    subject = "Science" if "Sci" in parts else "Math" if "Math" in parts else "English" if "Eng" in parts else "Subject"
    part_str = " (Part 1)" if "1" in parts[2:] else " (Part 2)" if "2" in parts[2:] else ""
    return f"Cambridge {subject} {book_type} {grade}{part_str}"

def md_inline_to_rl(text: str) -> str:
    if text is None:
        return ""
    s = str(text)
    s = s.replace(r'\(', '').replace(r'\)', '').replace(r'\[', '').replace(r'\]', '')
    s = s.replace(r'\times', ' x ').replace(r'\div', ' ÷ ').replace(r'\circ', '°')
    s = s.replace(r'\pm', '±').replace(r'\leq', '≤').replace(r'\geq', '≥')
    s = s.replace(r'\neq', '≠').replace(r'\approx', '≈').replace(r'\pi', 'π').replace(r'\sqrt', '√')
    s = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1/\2', s)
    s = s.replace('\\', '')
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(\S.+?)\*(?!\*)", r"<i>\1</i>", s)
    return s

# -----------------------------
# 7) VISUAL GENERATORS (Dual-Layer)
# -----------------------------
def generate_single_image(desc: str):
    clean_desc = re.sub(r"\s+", " ", (desc or "")).strip()

    # ATTEMPT 1: Try the primary model (gemini-3-pro-image-preview)
    try:
        img_resp = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[clean_desc],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in (img_resp.parts or []):
            if getattr(part, "inline_data", None):
                return part.inline_data.data
                
    except Exception as primary_e:
        print(f"Primary model failed (likely 503 Overloaded). Falling back to Imagen. Error: {primary_e}")
        
        # ATTEMPT 2: Fall back to the stable Imagen 3 API
        try:
            fallback_response = client.models.generate_images(
                model='imagen-3.0-generate-002',
                prompt=clean_desc,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9" 
                )
            )
            for generated_image in fallback_response.generated_images:
                return generated_image.image.image_bytes
                
        except Exception as fallback_e:
            print(f"Fallback model also failed: {fallback_e}")
            
    return None

def generate_pie_chart(data_str: str):
    try:
        labels, sizes = [], []
        for item in str(data_str).split(","):
            if ":" in item:
                k, v = item.split(":", 1)
                labels.append(k.strip())
                sizes.append(float(re.sub(r"[^\d\.]", "", v)))

        if not labels or not sizes or len(labels) != len(sizes):
            return None

        fig = Figure(figsize=(5, 5), dpi=200)
        FigureCanvas(fig)
        ax = fig.add_subplot(111)

        theme_colors = ["#00d4ff", "#fc8404", "#2ecc71", "#9b59b6", "#f1c40f", "#e74c3c"]
        ax.pie(
            sizes, labels=labels, autopct="%1.1f%%", startangle=140,
            colors=theme_colors[: len(labels)], textprops={"color": "black", "fontsize": 9}
        )
        ax.axis("equal")

        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
        return buf.getvalue()
    except Exception as e:
        print(f"Pie chart error: {e}")
    return None

def process_visual(prompt_data):
    trigger_type, data = prompt_data
    if trigger_type == "IMAGE_GEN":
        return generate_single_image(data)
    if trigger_type == "PIE_CHART":
        return generate_pie_chart(data)
    return None

# -----------------------------
# 8) PDF EXPORT
# -----------------------------
def create_pdf(content: str, images=None, filename="Question_Paper.pdf"):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Heading1"], fontSize=18,
        textColor=colors.HexColor("#00d4ff"), spaceAfter=12,
        alignment=TA_CENTER, fontName="Helvetica-Bold"
    )
    heading_style = ParagraphStyle(
        "CustomHeading", parent=styles["Heading2"], fontSize=14,
        spaceAfter=10, spaceBefore=10, fontName="Helvetica-Bold"
    )
    body_style = ParagraphStyle(
        "CustomBody", parent=styles["BodyText"], fontSize=11,
        spaceAfter=8, alignment=TA_LEFT, fontName="Helvetica"
    )

    story = []
    if not content:
        content = "⚠️ No content to export."

    lines = str(content).split("\n")
    start_index = 0
    for i, line in enumerate(lines[:5]):
        if line.strip().startswith("#"):
            start_index = i
            break
    lines = lines[start_index:]

    cleaned_lines = []
    skip_sources = False
    for line in lines:
        stripped = line.strip()
        if "[PDF_READY]" in stripped:
            continue
        if stripped.startswith("Source(s):") or stripped.startswith("**Source(s):**"):
            skip_sources = True
            continue
        if skip_sources:
            if not stripped or stripped.startswith("*") or stripped.startswith("-"):
                continue
            skip_sources = False
        clean_line = re.sub(r"\s*\(Source:.*?\)", "", line)
        cleaned_lines.append(clean_line)

    img_idx = 0
    table_rows = []

    def render_pending_table():
        nonlocal table_rows
        if not table_rows:
            return
        ncols = max(len(r) for r in table_rows)
        norm_rows = []
        for r in table_rows:
            r2 = list(r) + [""] * (ncols - len(r))
            norm_rows.append([Paragraph(md_inline_to_rl(c), body_style) for c in r2])
        t = Table(norm_rows, colWidths=[doc.width / max(1, ncols)] * ncols)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00d4ff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.18 * inch))
        table_rows = []

    for raw in cleaned_lines:
        line = raw.rstrip("\n")
        s = line.strip()

        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.split("|")[1:-1]]
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            table_rows.append(cells)
            continue
        else:
            render_pending_table()

        if not s:
            story.append(Spacer(1, 0.14 * inch))
            continue

        if s.startswith("IMAGE_GEN:") or s.startswith("PIE_CHART:"):
            if images and img_idx < len(images) and images[img_idx]:
                try:
                    img_stream = BytesIO(images[img_idx])
                    rl_reader = ImageReader(img_stream)
                    iw, ih = rl_reader.getSize()
                    aspect = ih / float(iw)
                    story.append(Spacer(1, 0.12 * inch))
                    story.append(RLImage(img_stream, width=4.6 * inch, height=4.6 * inch * aspect))
                    story.append(Spacer(1, 0.12 * inch))
                except Exception:
                    pass
            img_idx += 1
            continue

        if "mark scheme" in s.lower() and s.startswith("#"):
            story.append(PageBreak())
            story.append(Paragraph(md_inline_to_rl(re.sub(r"^#+\s*", "", s)), title_style))
            continue

        if s.startswith("# "):
            story.append(Paragraph(md_inline_to_rl(s[2:].strip()), title_style))
        elif s.startswith("## "):
            story.append(Paragraph(md_inline_to_rl(s[3:].strip()), heading_style))
        elif s.startswith("### "):
            story.append(Paragraph(f"<b>{md_inline_to_rl(s[4:].strip())}</b>", body_style))
        else:
            story.append(Paragraph(md_inline_to_rl(line), body_style))

    render_pending_table()
    story.append(Spacer(1, 0.28 * inch))
    story.append(Paragraph("<i>Generated by helix.ai - Your CIE Tutor</i>", body_style))
    doc.build(story)
    buffer.seek(0)
    return buffer

# -----------------------------
# 9) SYSTEM INSTRUCTION
# -----------------------------
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

### RULE 1: THE VISION & RAG SEARCH (CRITICAL)
- If the user provides an IMAGE, PDF, or TXT file, analyze it carefully.
- STEP 1: Search the attached PDF textbooks using OCR FIRST. Cite the book at the end like this: (Source: Cambridge Science Textbook 7).
- STEP 2: If the textbooks do not contain the answer, explicitly state: "I couldn't find this in your textbook, but here is what I found:"

### RULE 2: MATH ACCURACY (CRITICAL)
- When generating math questions and mark schemes, you MUST solve the equations step-by-step internally before writing the final mark scheme.
- Ensure the variables in the mark scheme EXACTLY match the variables used in the questions. Do not hallucinate numbers.

### RULE 3: QUESTION PAPERS (CRITICAL FORMATTING)
- SUBJECT RELEVANCE: NEVER put Science diagrams or questions in a Math paper, and vice versa!
- NO LATEX MATH: DO NOT use LaTeX for math formatting. NEVER use backslashes (\\) or commands like \\frac, \\times, \\div.
- PLAIN TEXT MATH ONLY: Use standard characters (/, x, *, ÷, ^).
- Tables: ALWAYS use standard Markdown tables. Do NOT use IMAGE_GEN for tables.
- Visuals: Use IMAGE_GEN for diagrams, PIE_CHART for pie charts.
- NUMBERING: Clean numbering 1., 2., 3. and sub-questions (a), (b), (c).
- MARKS: Put marks at end of the SAME LINE like "... [3]".
- CITATION RULE: List the source(s) only once at the very bottom.
- PDF TRIGGER: If, and ONLY IF, you generated a full formal question paper, append [PDF_READY] at the very end.

### RULE 5: VISUAL SYNTAX (STRICT)
- For diagrams:
  IMAGE_GEN: [Detailed description of the image, educational, white background]
- For pie charts (no AI):
  PIE_CHART: [Label1:Value1, Label2:Value2]
  Example: PIE_CHART: [Nitrogen:78, Oxygen:21, Argon:1]

### RULE 6: MARK SCHEME
- Put "## Mark Scheme" at the very bottom. No citations inside mark scheme.
"""

# -----------------------------
# 10) GOOGLE FILE API
# -----------------------------
@st.cache_resource(show_spinner=False)
def upload_textbooks():
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_9_SB_Eng.pdf", "CIE_9_WB_Eng.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf",
    ]
    active_files = {"sci": [], "math": [], "eng": []}

    msg_placeholder = st.empty()
    with msg_placeholder.chat_message("assistant"):
        st.markdown("""
        <div class="thinking-container">
            <span class="thinking-text"> 📚 Scanning Books...</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

    existing_server_files = {f.display_name.lower(): f for f in client.files.list() if f.display_name}
    pdf_map = {p.name.lower(): p for p in Path.cwd().rglob("*.pdf")}

    for target_name in target_filenames:
        t = target_name.lower()
        if t in existing_server_files:
            server_file = existing_server_files[t]
            if server_file.state.name == "ACTIVE":
                if "sci" in t:
                    active_files["sci"].append(server_file)
                elif "math" in t:
                    active_files["math"].append(server_file)
                elif "eng" in t:
                    active_files["eng"].append(server_file)
                continue

        found_path = pdf_map.get(t)
        if not found_path:
            continue

        try:
            uploaded = client.files.upload(
                file=str(found_path),
                config={"mime_type": "application/pdf", "display_name": found_path.name}
            )
            start = time.time()
            while uploaded.state.name == "PROCESSING":
                if time.time() - start > 180:
                    break
                time.sleep(3)
                uploaded = client.files.get(name=uploaded.name)

            if uploaded.state.name == "ACTIVE":
                if "sci" in t:
                    active_files["sci"].append(uploaded)
                elif "math" in t:
                    active_files["math"].append(uploaded)
                elif "eng" in t:
                    active_files["eng"].append(uploaded)
        except Exception:
            continue

    msg_placeholder.empty()
    return active_files

# -----------------------------
# 11) SMART RAG ROUTING
# -----------------------------
def select_relevant_books(query, file_dict):
    q = (query or "").lower()
    selected = []

    is_math = any(k in q for k in ["math", "algebra", "geometry", "calculate", "equation", "number", "fraction"])
    is_sci = any(k in q for k in ["science", "cell", "biology", "physics", "chemistry", "experiment", "gravity"])
    is_eng = any(k in q for k in ["english", "poem", "story", "essay", "writing", "grammar", "noun", "verb"])

    stage_7 = any(k in q for k in ["stage 7", "grade 6", "year 7"])
    stage_8 = any(k in q for k in ["stage 8", "grade 7", "year 8"])
    stage_9 = any(k in q for k in ["stage 9", "grade 8", "year 9"])

    has_subject = is_math or is_sci or is_eng
    has_stage = stage_7 or stage_8 or stage_9

    if not has_subject and not has_stage:
        return []

    if has_stage and not has_subject:
        is_math = is_sci = is_eng = True
    if has_subject and not has_stage:
        stage_8 = True

    def add_books(subject_key, active):
        if not active:
            return
        for book in file_dict.get(subject_key, []):
            name = (book.display_name or "").lower()
            if stage_7 and "cie_7" in name:
                selected.append(book)
            if stage_8 and "cie_8" in name:
                selected.append(book)
            if stage_9 and "cie_9" in name:
                selected.append(book)

    add_books("math", is_math)
    add_books("sci", is_sci)
    add_books("eng", is_eng)
    return selected[:3]

# -----------------------------
# 12) RENDER CHAT
# -----------------------------
if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()

for idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        display_content = (message.get("content") or "").replace("[PDF_READY]", "").strip()
        st.markdown(display_content)

        if message.get("images"):
            for img_bytes in message["images"]:
                if img_bytes:
                    st.image(img_bytes, width=420)

        if message.get("user_attachment_bytes"):
            mime = message.get("user_attachment_mime", "")
            name = message.get("user_attachment_name", "File")
            if "image" in mime:
                st.image(message["user_attachment_bytes"], width=320)
            elif "pdf" in mime:
                st.caption(f"📄 *Attached PDF Document: {name}*")
            elif "text" in mime or name.endswith(".txt"):
                st.caption(f"📝 *Attached Text Document: {name}*")

        if message["role"] == "assistant" and message.get("is_downloadable"):
            try:
                pdf_buffer = create_pdf(message.get("content") or "", images=message.get("images", []))
                st.download_button(
                    label="📥 Download Question Paper as PDF",
                    data=pdf_buffer,
                    file_name=f"Helix_Question_Paper_{idx}.pdf",
                    mime="application/pdf",
                    key=f"download_{st.session_state.current_thread_id}_{idx}",
                )
            except Exception:
                pass

# -----------------------------
# 13) MAIN LOOP
# -----------------------------
chat_input_data = st.chat_input(
    "Ask Helix... (Click the paperclip to upload a file!)",
    accept_file=True,
    file_type=["jpg", "jpeg", "png", "webp", "avif", "svg", "pdf", "txt"],
)

if chat_input_data:
    prompt = chat_input_data.text or ""
    uploaded_files = chat_input_data.files
    user_msg = {"role": "user", "content": prompt}
    file_bytes, file_mime, file_name = None, None, None

    if uploaded_files and len(uploaded_files) > 0:
        uf = uploaded_files[0]
        file_bytes = uf.getvalue()
        file_mime = uf.type
        file_name = uf.name
        user_msg["user_attachment_bytes"] = file_bytes
        user_msg["user_attachment_mime"] = file_mime
        user_msg["user_attachment_name"] = file_name

    st.session_state.messages.append(user_msg)
    save_chat_history()

    with st.chat_message("user"):
        st.markdown(prompt)
        if file_bytes:
            if "image" in (file_mime or ""):
                st.image(file_bytes, width=320)
            elif "pdf" in (file_mime or ""):
                st.caption(f"📄 *Attached: {file_name}*")
            elif "text/plain" in (file_mime or "") or (file_name or "").endswith(".txt"):
                st.caption(f"📝 *Attached: {file_name}*")

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()
        try:
            has_attachment = file_bytes is not None
            if has_attachment:
                relevant_books = select_relevant_books(prompt + " science stage 8", st.session_state.textbook_handles)
            else:
                relevant_books = select_relevant_books(prompt, st.session_state.textbook_handles)

            if relevant_books:
                book_names = [get_friendly_name(b.display_name) for b in relevant_books]
                st.caption(f"🔍 *Scanning Curriculum: {', '.join(book_names)}*")
            else:
                if has_attachment:
                    st.caption("🔍 *Analyzing attached file...*")
                else:
                    st.caption("⚡ *Quick reply (General Knowledge)*")

            thinking_placeholder.markdown("""
                <div class="thinking-container">
                    <span class="thinking-text">🧠 Reading & Looking...</span>
                    <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
                </div>
            """, unsafe_allow_html=True)

            current_prompt_parts = []
            temp_pdf_path = None

            if file_bytes:
                if "image" in (file_mime or ""):
                    current_prompt_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime))
                elif "pdf" in (file_mime or ""):
                    temp_pdf_path = f"temp_user_upload_{int(time.time())}.pdf"
                    with open(temp_pdf_path, "wb") as f:
                        f.write(file_bytes)
                    user_uploaded_pdf = client.files.upload(file=temp_pdf_path)
                    while user_uploaded_pdf.state.name == "PROCESSING":
                        time.sleep(1)
                        user_uploaded_pdf = client.files.get(name=user_uploaded_pdf.name)
                    current_prompt_parts.append(types.Part.from_uri(file_uri=user_uploaded_pdf.uri, mime_type="application/pdf"))
                elif "text/plain" in (file_mime or "") or (file_name or "").endswith(".txt"):
                    raw_text = file_bytes.decode("utf-8", errors="ignore")
                    current_prompt_parts.append(types.Part.from_text(
                        text=f"--- Attached Text File ({file_name}) ---\n{raw_text}\n--- End of File ---\n"
                    ))

            for book in relevant_books:
                friendly = get_friendly_name(book.display_name)
                current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly}]"))
                current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))

            current_prompt_parts.append(types.Part.from_text(
                text=f"Please read the user query and look at attached files. Check Cambridge textbooks for accuracy if provided.\n\nQuery: {prompt}"
            ))
            current_content = types.Content(role="user", parts=current_prompt_parts)

            history_contents = []
            text_msgs = [m for m in st.session_state.messages[:-1] if not m.get("is_greeting")]
            for msg in text_msgs[-7:]:
                role = "user" if msg["role"] == "user" else "model"
                history_contents.append(types.Content(
                    role=role, parts=[types.Part.from_text(text=msg.get("content") or "")]
                ))

            full_contents = history_contents + [current_content]

            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,
                    tools=[{"google_search": {}}],
                ),
            )

            bot_text = safe_response_text(text_response)
            if not bot_text.strip():
                bot_text = "⚠️ *Helix couldn't generate a text response this time.* Try rephrasing your question."

            thinking_placeholder.empty()

            visual_prompts = re.findall(r"(IMAGE_GEN|PIE_CHART):\s*\[(.*?)\]", bot_text)
            generated_images = []

            if visual_prompts:
                img_thinking = st.empty()
                img_thinking.markdown("""
                    <div class="thinking-container">
                        <span class="thinking-text">🖌️ Processing diagrams & charts...</span>
                        <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
                    </div>
                """, unsafe_allow_html=True)
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    generated_images = list(executor.map(process_visual, visual_prompts))
                img_thinking.empty()

                for i, img in enumerate(generated_images):
                    if img is None:
                        bot_text += f"\n\n⚠️ *Helix tried to draw a diagram here, but the image generator is currently overloaded (High Demand). Please try again later.*"

            # PDF button detection
            is_downloadable = (
                "[PDF_READY]" in bot_text or
                ("## Mark Scheme" in bot_text and re.search(r"\[\d+\]", bot_text) is not None)
            )

            bot_msg = {
                "role": "assistant",
                "content": bot_text,
                "is_downloadable": is_downloadable,
                "images": generated_images,
            }

            st.session_state.messages.append(bot_msg)

            # --- AUTO-TITLE LOGIC ---
            if is_authenticated:
                user_msg_count = sum(1 for m in st.session_state.messages if m.get("role") == "user")
                if user_msg_count > 0 and (user_msg_count - 1) % 5 == 0:
                    coll_ref = get_threads_collection()
                    if coll_ref and st.session_state.current_thread_id:
                        thread_doc = coll_ref.document(st.session_state.current_thread_id).get()
                        user_edited = False
                        if thread_doc.exists:
                            user_edited = thread_doc.to_dict().get("user_edited_title", False)

                        if not user_edited:
                            new_title = generate_chat_title(client, st.session_state.messages)
                            coll_ref.document(st.session_state.current_thread_id).set({"title": new_title}, merge=True)

            save_chat_history()
            st.rerun()

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")

        finally:
            try:
                if "temp_pdf_path" in locals() and temp_pdf_path and os.path.exists(temp_pdf_path):
                    os.remove(temp_pdf_path)
            except Exception:
                pass
