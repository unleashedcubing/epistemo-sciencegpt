import streamlit as st
import os
import time
import re
import uuid
import json
import concurrent.futures
import base64
from pathlib import Path
from io import BytesIO
from PIL import Image

from google import genai
from google.genai import types
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

# Matplotlib
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

TEACHER_VERIFICATION_CODE = st.secrets.get("TEACHER_VERIFICATION_CODE", "7nI9sL0")

# -----------------------------
# 1.5) GRADE <-> STAGE MAPPING
# -----------------------------
GRADE_TO_STAGE = {"Grade 6": "Stage 7", "Grade 7": "Stage 8", "Grade 8": "Stage 9"}
STAGE_TO_GRADE = {v: k for k, v in GRADE_TO_STAGE.items()}

NUM_WORDS = {"six": "6", "seven": "7", "eight": "8", "nine": "9", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}

def normalize_stage_text(s: str) -> str:
    s = (s or "").lower()
    for w, d in NUM_WORDS.items():
        s = re.sub(rf"\b{w}\b", d, s)
    return s

def infer_stage_from_text(text: str):
    t = normalize_stage_text(text or "")
    if re.search(r"\b(grade|class|year)\W*6\b", t): return "Stage 7"
    if re.search(r"\b(grade|class|year)\W*7\b", t): return "Stage 8"
    if re.search(r"\b(grade|class|year)\W*8\b", t): return "Stage 9"
    if re.search(r"\bstage\W*7\b", t): return "Stage 7"
    if re.search(r"\bstage\W*8\b", t): return "Stage 8"
    if re.search(r"\bstage\W*9\b", t): return "Stage 9"
    return None

# -----------------------------
# 2) AUTH & FIRESTORE
# -----------------------------
if hasattr(st, "user"):
    auth_object = st.user
elif hasattr(st, "experimental_user"):
    auth_object = st.experimental_user
else:
    st.error("Your Streamlit version is too old for Google Login.")
    st.stop()

is_authenticated = getattr(auth_object, "is_logged_in", False)

@st.cache_resource
def get_firestore_client():
    if "firebase" in st.secrets:
        key_dict = dict(st.secrets["firebase"])
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds)
    return None

db = get_firestore_client()

def get_student_class_data(student_email):
    if not db: return None
    class_query = db.collection("classes").where(
        filter=firestore.FieldFilter("students", "array_contains", student_email)
    ).limit(1).stream()
    for c in class_query:
        return c.to_dict()
    return None

def get_user_profile(email):
    if not db: return {"role": "student"}
    doc_ref = db.collection("users").document(email)
    doc = doc_ref.get()
    if doc.exists:
        profile = doc.to_dict()
        if not profile.get("display_name") and is_authenticated:
            google_name = getattr(auth_object, "name", None) or email.split("@")[0]
            doc_ref.update({"display_name": google_name})
            profile["display_name"] = google_name
        return profile
    else:
        google_name = getattr(auth_object, "name", None) or email.split("@")[0] if is_authenticated else email.split("@")[0]
        default_profile = {
            "role": "undefined",
            "teacher_id": None,
            "display_name": google_name,
            "grade": "Grade 6" 
        }
        
        doc_ref.set(default_profile)
        return default_profile

def create_global_class(class_id, teacher_email, grade, section):
    clean_id = class_id.strip().upper()
    if not clean_id or not db: return False, "Database error."
    class_ref = db.collection("classes").document(clean_id)

    @firestore.transactional
    def check_and_create(transaction, ref):
        snap = ref.get(transaction=transaction)
        if snap.exists:
            return False, f"Class '{clean_id}' already exists globally!"
        transaction.set(ref, {
            "created_by": teacher_email,
            "created_at": time.time(),
            "grade": grade,
            "section": section,
            "students": [],
            "subjects": []
        })
        return True, f"Class '{clean_id}' created successfully!"

    transaction = db.transaction()
    return check_and_create(transaction, class_ref)

user_role = "guest"
if is_authenticated:
    user_email = auth_object.email
    user_profile = get_user_profile(user_email)
    user_role = user_profile.get("role", "undefined")

# -----------------------------
# THREAD HELPERS
# -----------------------------
def get_threads_collection():
    if is_authenticated and db is not None:
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
        except Exception: pass
    return []

def get_default_greeting():
    return [{
        "role": "assistant",
        "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizzes!\nYou can also **attach photos, PDFs, or text files directly in the chat box below!** 📸📄\n\nWhat are we learning today?",
        "is_greeting": True,
    }]

def load_chat_history(thread_id):
    coll_ref = get_threads_collection()
    if coll_ref and thread_id:
        try:
            doc = coll_ref.document(thread_id).get()
            if doc.exists: return doc.to_dict().get("messages", [])
        except Exception: pass
    return get_default_greeting()

def compress_image_for_db(image_bytes: bytes) -> str:
    try:
        if not image_bytes: return None
        img = Image.open(BytesIO(image_bytes))
        if img.mode != 'RGB': img = img.convert('RGB')
        img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception: return None

def save_chat_history():
    coll_ref = get_threads_collection()
    if not coll_ref: return
    current_id = st.session_state.current_thread_id
    safe_messages = []
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
            
            qn = normalize_stage_text(content_str)
            if re.search(r"\b(stage\W*7|grade\W*6|class\W*6|year\W*6)\b", qn): detected_grades.add("Grade 6")
            if re.search(r"\b(stage\W*8|grade\W*7|class\W*7|year\W*7)\b", qn): detected_grades.add("Grade 7")
            if re.search(r"\b(stage\W*9|grade\W*8|class\W*8|year\W*8)\b", qn): detected_grades.add("Grade 8")

        db_images = []
        if msg.get("images"):
            for img_bytes in msg["images"]:
                if img_bytes:
                    c = compress_image_for_db(img_bytes)
                    if c: db_images.append(c)
        elif msg.get("db_images"): db_images = msg["db_images"]

        safe_messages.append({
            "role": str(role), "content": content_str,
            "is_greeting": bool(msg.get("is_greeting", False)),
            "is_downloadable": bool(msg.get("is_downloadable", False)),
            "db_images": db_images
        })

    data = {
        "messages": safe_messages,
        "updated_at": time.time(),
        "metadata": {"subjects": list(detected_subjects), "grades": list(detected_grades)},
    }
    try: coll_ref.document(current_id).set(data, merge=True)
    except Exception as e: st.toast(f"⚠️ Database Error: Could not save chat - {e}")

# -----------------------------
# PDF HELPER
# -----------------------------
def md_inline_to_rl(text: str) -> str:
    if text is None: return ""
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

def create_pdf(content: str, images=None, filename="Question_Paper.pdf"):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=0.75*inch, leftMargin=0.75*inch,
        topMargin=0.75*inch, bottomMargin=0.75*inch
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CustomTitle", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#00d4ff"), spaceAfter=12, alignment=TA_CENTER, fontName="Helvetica-Bold")
    heading_style = ParagraphStyle("CustomHeading", parent=styles["Heading2"], fontSize=14, spaceAfter=10, spaceBefore=10, fontName="Helvetica-Bold")
    body_style = ParagraphStyle("CustomBody", parent=styles["BodyText"], fontSize=11, spaceAfter=8, alignment=TA_LEFT, fontName="Helvetica")

    story = []
    if not content: content = "⚠️ No content to export."
    lines = str(content).split("\n")
    start_index = next((i for i, line in enumerate(lines[:5]) if line.strip().startswith("#")), 0)
    lines = lines[start_index:]

    cleaned_lines = []
    skip_sources = False
    for line in lines:
        stripped = line.strip()
        if "[PDF_READY]" in stripped: continue
        if stripped.startswith("Source(s):") or stripped.startswith("**Source(s):**"):
            skip_sources = True
            continue
        if skip_sources:
            if not stripped or stripped.startswith("*") or stripped.startswith("-"): continue
            skip_sources = False
        clean_line = re.sub(r"\s*\(Source:.*?\)", "", line)
        cleaned_lines.append(clean_line)

    img_idx = 0
    table_rows = []

    def render_pending_table():
        nonlocal table_rows
        if not table_rows: return
        ncols = max(len(r) for r in table_rows)
        norm_rows = []
        for r in table_rows:
            r2 = list(r) + [""] * (ncols - len(r))
            norm_rows.append([Paragraph(md_inline_to_rl(c), body_style) for c in r2])
        t = Table(norm_rows, colWidths=[doc.width / max(1, ncols)] * ncols)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00d4ff")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"), ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")), ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.18*inch))
        table_rows = []

    for raw in cleaned_lines:
        s = raw.strip()
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.split("|")[1:-1]]
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c): continue
            table_rows.append(cells)
            continue
        else:
            render_pending_table()
        if not s:
            story.append(Spacer(1, 0.14*inch))
            continue
        if s.startswith("IMAGE_GEN:") or s.startswith("PIE_CHART:"):
            if images and img_idx < len(images) and images[img_idx]:
                try:
                    img_stream = BytesIO(images[img_idx])
                    rl_reader = ImageReader(img_stream)
                    iw, ih = rl_reader.getSize()
                    aspect = ih / float(iw)
                    story.append(Spacer(1, 0.12*inch))
                    story.append(RLImage(img_stream, width=4.6*inch, height=4.6*inch*aspect))
                    story.append(Spacer(1, 0.12*inch))
                except Exception: pass
            img_idx += 1
            continue
        if "mark scheme" in s.lower() and s.startswith("#"):
            story.append(PageBreak())
            story.append(Paragraph(md_inline_to_rl(re.sub(r"^#+\s*", "", s)), title_style))
            continue
        if s.startswith("# "): story.append(Paragraph(md_inline_to_rl(s[2:].strip()), title_style))
        elif s.startswith("## "): story.append(Paragraph(md_inline_to_rl(s[3:].strip()), heading_style))
        elif s.startswith("### "): story.append(Paragraph(f"<b>{md_inline_to_rl(s[4:].strip())}</b>", body_style))
        else: story.append(Paragraph(md_inline_to_rl(raw), body_style))

    render_pending_table()
    story.append(Spacer(1, 0.28*inch))
    story.append(Paragraph("<i>Generated by helix.ai - Your CIE Tutor</i>", body_style))
    doc.build(story)
    buffer.seek(0)
    return buffer

def safe_response_text(resp) -> str:
    try:
        t = getattr(resp, "text", None)
        if t: return str(t)
    except Exception: pass
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            parts = getattr(content, "parts", None) or []
            texts = [getattr(p, "text", None) for p in parts if getattr(p, "text", None)]
            if texts: return "\n".join(texts)
    except Exception: pass
    return ""

def generate_chat_title(client, messages):
    try:
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        if not user_msgs: return "New Chat"
        prompt = "Summarize this conversation context into a very short, punchy chat title (maximum 4 words). Do not use quotes or punctuation. Context: " + "\n".join(user_msgs[-3:])
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=[prompt],
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=15),
        )
        title = safe_response_text(response).strip().replace('"', '').replace("'", "")
        return title if title else "New Chat"
    except Exception: return "New Chat"

# -----------------------------
# 3) SESSION STATE & DIALOGS
# -----------------------------
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = str(uuid.uuid4())
if "messages" not in st.session_state: st.session_state.messages = get_default_greeting()
if "delete_requested_for" not in st.session_state: st.session_state.delete_requested_for = None

@st.dialog("⚠️ Maximum Chats Reached")
def confirm_new_chat_dialog(oldest_thread_id):
    st.write("You have hit the maximum limit of **15 saved chats**.")
    st.write("If you create a new chat, your oldest chat will be permanently deleted.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True): st.rerun()
    with col2:
        if st.button("Yes, Create New", type="primary", use_container_width=True):
            try: get_threads_collection().document(oldest_thread_id).delete()
            except Exception: pass
            st.session_state.current_thread_id = str(uuid.uuid4())
            st.session_state.messages = get_default_greeting()
            st.rerun()

@st.dialog("🗑️ Delete Chat")
def confirm_delete_chat_dialog(thread_id_to_delete):
    st.write("Are you sure you want to permanently delete this chat?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            st.session_state.delete_requested_for = None
            st.rerun()
    with col2:
        if st.button("Yes, Delete", type="primary", use_container_width=True):
            try: get_threads_collection().document(thread_id_to_delete).delete()
            except Exception: pass
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
        get_threads_collection().document(thread_data["id"]).set({"title": new_title, "user_edited_title": True}, merge=True)
        st.rerun()
    st.divider()
    if st.button("🗑️ Delete Chat", key=f"del_btn_set_{thread_data['id']}", type="primary", use_container_width=True):
        st.session_state.delete_requested_for = thread_data['id']
        st.rerun()

# =====================================================================
# 🔴 HELIX ADMIN MODE
# =====================================================================
ADMIN_VERIFICATION_CODE = st.secrets.get("ADMIN_VERIFICATION_CODE")

ADMIN_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: linear-gradient(160deg, #1a0008 0%, #0d0010 60%, #0b000d 100%) !important; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #2a0010 0%, #0d000a 100%) !important; }
.admin-header { background: linear-gradient(135deg, rgba(225,29,72,0.18), rgba(153,0,30,0.12)); border: 1px solid rgba(225,29,72,0.35); border-radius: 16px; padding: 20px 28px; margin-bottom: 24px; }
.admin-title { font-size: 1.9rem; font-weight: 800; background: linear-gradient(90deg, #ff4d6d, #ff8fa3); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
.stat-card { background: rgba(225,29,72,0.08); border: 1px solid rgba(225,29,72,0.2); border-radius: 14px; padding: 18px 20px; text-align: center; margin-bottom: 15px; }
.stat-number { font-size: 2.2rem; font-weight: 800; color: #ff4d6d; }
.stat-label { font-size: 0.78rem; color: rgba(255,150,160,0.6); text-transform: uppercase; }
.admin-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-bottom: 20px; }
.admin-table th { background: rgba(225,29,72,0.15); color: #ff8fa3; padding: 10px; text-align: left; }
.admin-table td { padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); color: rgba(255,200,205,0.85); }
.section-header { font-size: 1.1rem; font-weight: 700; color: #ff6b81; border-left: 3px solid #e11d48; padding-left: 12px; margin: 20px 0 14px; }
.admin-login-box { max-width: 420px; margin: 80px auto; background: rgba(225,29,72,0.07); border: 1px solid rgba(225,29,72,0.25); border-radius: 20px; padding: 40px 36px; text-align: center; }
</style>
"""

from datetime import datetime

def log_audit(admin_email, action, target_type, target_id):
    if db: db.collection("admin_audit").add({"admin_email": admin_email, "action": action, "target_type": target_type, "target_id": target_id, "timestamp": time.time()})

def render_admin_panel():
    st.markdown(ADMIN_CSS, unsafe_allow_html=True)
    
    # User must be authenticated via Google first
    if not is_authenticated:
        st.error("You must log in with Google first to access the Admin Panel.")
        if st.button("Return Home"):
            st.session_state["current_page"] = "chat"
            st.rerun()
        return

    admin_email = auth_object.email
    allowed_admins = st.secrets.get("ADMIN_EMAILS", [])

    # Double-check they are on the allowed list
    if admin_email not in allowed_admins:
        st.error("Your account is not authorized for Admin access.")
        if st.button("Return Home"):
            st.session_state["current_page"] = "chat"
            st.rerun()
        return

    # --- ADMIN LOGIN GATE ---
    if not st.session_state.get("admin_authenticated"):
        st.markdown(f'<div class="admin-login-box"><h2 style="color:#ff4d6d;margin-bottom:6px;">🔐 Admin Access</h2><p style="color:rgba(255,150,160,0.6);font-size:0.85rem;">Welcome {admin_email}. Enter your verification code.</p></div>', unsafe_allow_html=True)
        with st.form("admin_login"):
            code = st.text_input("Admin Verification Code", type="password")
            if st.form_submit_button("🔓 Access Admin Panel"):
                if code.strip() == ADMIN_VERIFICATION_CODE:
                    st.session_state["admin_authenticated"] = True
                    st.session_state["admin_email"] = admin_email
                    log_audit(admin_email, "ADMIN_LOGIN", "session", "login")
                    st.rerun()
                else: st.error("❌ Invalid code.")
        return

    st.markdown(f'<div class="admin-header"><div class="admin-title">⚙️ Helix Admin Console</div><div style="color:rgba(255,150,160,0.6);font-size:0.85rem;margin-top:4px;">Logged in as {admin_email}</div></div>', unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("<b style='color:#ff4d6d'>ADMIN NAVIGATION</b>", unsafe_allow_html=True)
        admin_page = st.radio("", ["📊 Dashboard", "🎓 Students", "👩‍🏫 Teachers", "🏫 Classes", "🧪 AI Debug Lab"], label_visibility="collapsed")
        st.markdown("---")
        if st.button("🚪 Exit Admin Mode", use_container_width=True):
            st.session_state["admin_authenticated"] = False
            st.session_state["current_page"] = "chat"
            st.rerun()

    # --- DASHBOARD ---
    if admin_page == "📊 Dashboard":
        st.markdown('<div class="section-header">📊 System Overview</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        try:
            c1.markdown(f'<div class="stat-card"><div class="stat-number">{len(list(db.collection("students").stream()))}</div><div class="stat-label">Students</div></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="stat-card"><div class="stat-number">{len(list(db.collection("teachers").stream()))}</div><div class="stat-label">Teachers</div></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="stat-card"><div class="stat-number">{len(list(db.collection("classes").stream()))}</div><div class="stat-label">Classes</div></div>', unsafe_allow_html=True)
        except Exception as e: st.error(f"DB Error: {e}")

    # --- STUDENTS ---
    elif admin_page == "🎓 Students":
        st.markdown('<div class="section-header">🎓 Manage Students</div>', unsafe_allow_html=True)
        try:
            students = [{"id": d.id, **d.to_dict()} for d in db.collection("students").stream()]
            if students:
                rows = "".join(f"<tr><td>{s.get('name','—')}</td><td>{s.get('email','—')}</td><td>{s.get('grade','—')}</td><td><code>{s['id']}</code></td></tr>" for s in students)
                st.markdown(f'<table class="admin-table"><thead><tr><th>Name</th><th>Email</th><th>Grade</th><th>Doc ID</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        except Exception as e: st.error(str(e))
        
        st.markdown('<div class="section-header">🗑️ Delete Student</div>', unsafe_allow_html=True)
        del_id = st.text_input("Enter Student Document ID or Email to Delete")
        cascade = st.checkbox("Also delete their chat threads and analytics history", value=True)
        if st.button("🗑️ Permanently Delete Student", type="primary"):
            if del_id:
                try:
                    db.collection("students").document(del_id).delete()
                    db.collection("users").document(del_id).delete()
                    if cascade:
                        for t in db.collection("users").document(del_id).collection("threads").stream(): t.reference.delete()
                        for a in db.collection("users").document(del_id).collection("analytics").stream(): a.reference.delete()
                    log_audit(admin_email, "DELETE_STUDENT", "student", del_id)
                    st.success(f"Deleted student {del_id}")
                except Exception as e: st.error(str(e))

    # --- TEACHERS ---
    elif admin_page == "👩‍🏫 Teachers":
        st.markdown('<div class="section-header">👩‍🏫 Manage Teachers</div>', unsafe_allow_html=True)
        try:
            teachers = [{"id": d.id, **d.to_dict()} for d in db.collection("teachers").stream()]
            if teachers:
                rows = "".join(f"<tr><td>{t.get('name','—')}</td><td>{t.get('email','—')}</td><td><code>{t['id']}</code></td></tr>" for t in teachers)
                st.markdown(f'<table class="admin-table"><thead><tr><th>Name</th><th>Email</th><th>Doc ID</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        except Exception as e: st.error(str(e))
        del_t = st.text_input("Teacher Doc ID to delete")
        if st.button("Delete Teacher", type="primary") and del_t:
            db.collection("teachers").document(del_t).delete()
            st.success("Deleted")

    # --- CLASSES ---
    elif admin_page == "🏫 Classes":
        st.markdown('<div class="section-header">🏫 Manage Classes</div>', unsafe_allow_html=True)
        try:
            classes = [{"id": d.id, **d.to_dict()} for d in db.collection("classes").stream()]
            if classes:
                rows = "".join(f"<tr><td>{c.get('name','—')}</td><td>{c.get('stage','—')}</td><td><code>{c['id']}</code></td></tr>" for c in classes)
                st.markdown(f'<table class="admin-table"><thead><tr><th>Name</th><th>Stage</th><th>Doc ID</th></tr></thead><tbody>{rows}</tbody></table>', unsafe_allow_html=True)
        except Exception as e: st.error(str(e))
        del_c = st.text_input("Class Doc ID to delete")
        if st.button("Delete Class", type="primary") and del_c:
            db.collection("classes").document(del_c).delete()
            st.success("Deleted")

    # --- AI DEBUG LAB ---
    elif admin_page == "🧪 AI Debug Lab":
        st.markdown('<div class="section-header">🧪 AI Debug Lab</div>', unsafe_allow_html=True)
        m_choice = st.selectbox("Model", ["gemini-2.5-flash-preview-04-17", "gemini-2.0-flash"])
        d_prompt = st.text_area("User Prompt")
        if st.button("▶️ Run Prompt"):
            with st.spinner("Running..."):
                try:
                    resp = client.models.generate_content(model=m_choice, contents=d_prompt)
                    raw_out = getattr(resp, "text", "") or ""
                    st.markdown("#### 📄 Raw Output")
                    st.code(raw_out, language="markdown")
                except Exception as e: st.error(f"Error: {e}")


# --- THE ROUTER HOOK ---
if st.session_state.get("current_page") == "admin":
    render_admin_panel()
    st.stop()
# =====================================================================


# -----------------------------
# 4) SIDEBAR
# -----------------------------
with st.sidebar:
    st.title("Account Settings")
    
    raw_admins = st.secrets.get("ADMIN_EMAILS", [])
    allowed_admins = [email.lower() for email in raw_admins]
    
    if is_authenticated and user_email:

        current_user_lower = user_email.lower()

        if current_user_lower in allowed_admins:
            if st.button("⚙️ Admin Panel"):
                st.session_state["current_page"] = "admin"
                st.rerun()



    if not is_authenticated:
        st.markdown("You are chatting as a Guest!\nLog in with Google to save history!")
        if st.button("Log in with Google", type="primary", use_container_width=True):
            st.login(provider="google")
    else:
        username = getattr(auth_object, "name", None) or (user_email.split("@")[0] if user_email else "User")
        role_display = f"\n{user_role.capitalize()}" if user_role not in ["undefined", "guest"] else ""
        st.success(f"Welcome back, {username}!{role_display}")
        
        if st.button("Log out"):
            st.logout()

        st.divider()

        if user_role == "student":
            assigned_teacher = user_profile.get("teacher_id", None)
            if not assigned_teacher:
                with st.expander("🎓 Are you a Teacher?"):
                    st.caption("Enter your school's verification code to unlock the Teacher Dashboard.")
                    code_input = st.text_input("Teacher Code", type="password")
                    if st.button("Verify Code"):
                        if code_input == TEACHER_VERIFICATION_CODE:
                            db.collection("users").document(user_email).update({"role": "teacher"})
                            st.success("Verified! Refreshing app...")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Invalid Code.")
            else:
                student_class_name = "Unknown Class"
                if db is not None:
                    class_query = db.collection("classes").where(
                        filter=firestore.FieldFilter("students", "array_contains", user_email)
                    ).limit(1).stream()
                    
                    for c in class_query:
                        student_class_name = c.id
                        break
                        
                st.info(f"🏫 Connected to class:\n**{student_class_name}**")

    sidebar_threads = get_all_threads() if is_authenticated else []

    if st.button("➕ New Chat", use_container_width=True):
        if is_authenticated and len(sidebar_threads) >= 15:
            confirm_new_chat_dialog(sidebar_threads[-1]["id"])
        else:
            st.session_state.current_thread_id = str(uuid.uuid4())
            st.session_state.messages = get_default_greeting()
            st.rerun()

    if is_authenticated:
        st.subheader("Recent Chats")
        if not sidebar_threads: st.caption("*Your saved chats will appear here.*")
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

# -----------------------------
# GEMINI INIT & FILE HELPERS
# -----------------------------
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    if "GOOGLE_API_KEY" in st.secrets: api_key = st.secrets["GOOGLE_API_KEY"]
    else: st.error("🚨 GOOGLE_API_KEY not found."); st.stop()
try: client = genai.Client(api_key=api_key)
except Exception as e: st.error(f"🚨 Failed to initialize Gemini Client: {e}"); st.stop()


def get_friendly_name(filename: str) -> str:
    if not filename: return "Cambridge Textbook"
    name = filename.replace(".pdf", "").replace(".PDF", "")
    parts = name.split("_")
    if len(parts) < 3 or parts[0] != "CIE": return filename
    grade = parts[1]
    book_type = "Workbook" if "WB" in parts else "Textbook"
    if "ANSWERS" in parts: book_type += " Answers"
    subject = "Science" if "Sci" in parts else "Math" if "Math" in parts else "English" if "Eng" in parts else "Subject"
    part_str = " (Part 1)" if "1" in parts[2:] else " (Part 2)" if "2" in parts[2:] else ""
    return f"Cambridge {subject} {book_type} {grade}{part_str}"

@st.cache_resource(show_spinner=False)
def upload_textbooks():
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf", "CIE_9_SB_Eng.pdf", "CIE_9_WB_Eng.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf", "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf", "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf",
    ]
    active_files = {"sci": [], "math": [], "eng": []}
    msg_placeholder = st.empty()
    with msg_placeholder.chat_message("assistant"):
        st.markdown("""<div class="thinking-container"><span class="thinking-text">📚 Scanning Books...</span><div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div></div>""", unsafe_allow_html=True)
    existing_server_files = {f.display_name.lower(): f for f in client.files.list() if f.display_name}
    pdf_map = {p.name.lower(): p for p in Path.cwd().rglob("*.pdf")}

    for target_name in target_filenames:
        t = target_name.lower()
        if t in existing_server_files:
            server_file = existing_server_files[t]
            if server_file.state.name == "ACTIVE":
                if "sci" in t: active_files["sci"].append(server_file)
                elif "math" in t: active_files["math"].append(server_file)
                elif "eng" in t: active_files["eng"].append(server_file)
                continue
        found_path = pdf_map.get(t)
        if not found_path: continue
        try:
            uploaded = client.files.upload(file=str(found_path), config={"mime_type": "application/pdf", "display_name": found_path.name})
            start = time.time()
            while uploaded.state.name == "PROCESSING":
                if time.time() - start > 180: break
                time.sleep(3)
                uploaded = client.files.get(name=uploaded.name)
            if uploaded.state.name == "ACTIVE":
                if "sci" in t: active_files["sci"].append(uploaded)
                elif "math" in t: active_files["math"].append(uploaded)
                elif "eng" in t: active_files["eng"].append(uploaded)
        except Exception: continue
    msg_placeholder.empty()
    return active_files

def select_relevant_books(query, file_dict):
    qn = normalize_stage_text(query)
    selected = []
    is_math = any(k in qn for k in ["math", "algebra", "geometry", "calculate", "equation", "number", "fraction"])
    is_sci = any(k in qn for k in ["science", "cell", "biology", "physics", "chemistry", "experiment", "gravity"])
    is_eng = any(k in qn for k in ["english", "poem", "story", "essay", "writing", "grammar", "noun", "verb"])
    
    explicit_stage = infer_stage_from_text(qn)
    stage_7 = (explicit_stage == "Stage 7")
    stage_8 = (explicit_stage == "Stage 8")
    stage_9 = (explicit_stage == "Stage 9")
    has_subject = is_math or is_sci or is_eng
    has_stage = stage_7 or stage_8 or stage_9
    
    if not has_subject and not has_stage: return []
    if has_stage and not has_subject: is_math = is_sci = is_eng = True
    if has_subject and not has_stage: stage_8 = True # default

    def add_books(subject_key, active):
        if not active: return
        for book in file_dict.get(subject_key, []):
            name = (book.display_name or "").lower()
            if stage_7 and "cie_7" in name: selected.append(book)
            if stage_8 and "cie_8" in name: selected.append(book)
            if stage_9 and "cie_9" in name: selected.append(book)

    add_books("math", is_math)
    add_books("sci", is_sci)
    add_books("eng", is_eng)
    return selected[:3]

# ==========================================
# APP ROUTING: TEACHER DASHBOARD
# ==========================================
render_chat_interface = False 

if user_role == "teacher":
    st.markdown("<div class='big-title' style='color:#fc8404;'>👨‍🏫 helix.ai / Teacher</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>Classroom Management & AI Assistant</div>", unsafe_allow_html=True)

    AVAILABLE_SUBJECTS = ["Math", "Biology", "Chemistry", "Physics", "English"]

    student_docs_raw = db.collection("users").where(filter=firestore.FieldFilter("teacher_id", "==", user_email)).stream()
    roster = list(student_docs_raw)

    teacher_menu = st.radio(
        "Teacher Menu",
        ["⚙️ Class Management", "📊 Student Analytics", "📝 Assign Papers", "💬 AI Chat"],
        horizontal=True,
        label_visibility="collapsed"
    )
    st.divider()

    # ── MENU 1: CLASS MANAGEMENT
    if teacher_menu == "⚙️ Class Management":
        st.subheader("🏫 Class Management")
        with st.form("create_class_form", clear_on_submit=True):
            cc1, cc2, cc3 = st.columns([0.4, 0.3, 0.3])
            with cc1: grade_choice = st.selectbox("Grade", ["Grade 6", "Grade 7", "Grade 8"])
            with cc2: section_choice = st.selectbox("Section", ["A", "B", "C", "D"])
            with cc3:
                st.write("")
                submit_class = st.form_submit_button("➕ Create", use_container_width=True)
            if submit_class:
                grade_num = grade_choice.split()[-1]
                class_id = f"{grade_num}{section_choice}".upper()
                success, msg = create_global_class(class_id, user_email, grade_choice, section_choice)
                if success: st.success(msg); time.sleep(1); st.rerun()
                else: st.error(msg)

        st.divider()
        st.subheader("Add Students to a Class")
        my_classes_raw = list(db.collection("classes").where(filter=firestore.FieldFilter("created_by", "==", user_email)).stream())
        if my_classes_raw:
            class_names = [c.id for c in my_classes_raw]
            sel_class = st.selectbox("Select Class to Add Student:", class_names, key="add_student_class_sel")
            with st.form("add_student_form", clear_on_submit=True):
                c_em, c_btn = st.columns([0.8, 0.2])
                with c_em: new_email = st.text_input("Student Email Address")
                with c_btn:
                    st.write("")
                    submit_stud = st.form_submit_button("➕ Add", use_container_width=True)
                if submit_stud and new_email:
                    cln_email = new_email.strip().lower()
                    db.collection("users").document(cln_email).set({"role": "student", "teacher_id": user_email}, merge=True)
                    db.collection("classes").document(sel_class).update({"students": firestore.ArrayUnion([cln_email])})
                    st.success(f"Added {cln_email} to {sel_class}!")
                    time.sleep(1)
                    st.rerun()

        st.divider()
        st.subheader("Your Active Classes")
        if not my_classes_raw: st.info("You haven't created any classes yet.")
        else:
            for c in my_classes_raw:
                c_data = c.to_dict()
                c_name = c.id
                c_subj = c_data.get("subjects", [])
                c_studs = c_data.get("students", [])

                with st.expander(f"📁 {c_name}  ·  {len(c_studs)} Students  ·  📚 {', '.join(c_subj) if c_subj else 'No subjects'}"):
                    st.markdown("**Subjects You Teach in This Class:**")
                    new_subjs = []
                    s_cols = st.columns(len(AVAILABLE_SUBJECTS))
                    for i, subject in enumerate(AVAILABLE_SUBJECTS):
                        with s_cols[i]:
                            if st.checkbox(subject, value=(subject in c_subj), key=f"subj_{c_name}_{subject}"):
                                new_subjs.append(subject)
                    c_save, c_del = st.columns([0.7, 0.3])
                    with c_save:
                        if st.button("💾 Save Subjects", key=f"save_subj_{c_name}", use_container_width=True):
                            db.collection("classes").document(c_name).update({"subjects": new_subjs})
                            st.success("Saved!"); time.sleep(0.8); st.rerun()
                    with c_del:
                        if st.button("🗑️ Delete Class", key=f"del_class_{c_name}", type="primary", use_container_width=True):
                            db.collection("classes").document(c_name).delete()
                            st.rerun()

                    st.markdown("**Students in this class:**")
                    if not c_studs: st.caption("No students added yet.")
                    else:
                        for s_email in c_studs:
                            s_doc = db.collection("users").document(s_email).get()
                            s_name = s_doc.to_dict().get("display_name", s_email.split("@")[0]) if s_doc.exists else s_email.split("@")[0]
                            r1, r2 = st.columns([0.85, 0.15])
                            with r1: st.write(f"🎓 **{s_name}** ({s_email})")
                            with r2:
                                if st.button("Remove", key=f"rem_{c_name}_{s_email}", use_container_width=True):
                                    db.collection("classes").document(c_name).update({"students": firestore.ArrayRemove([s_email])})
                                    db.collection("users").document(s_email).update({"teacher_id": None})
                                    st.rerun()

    # ── MENU 2: STUDENT ANALYTICS
    elif teacher_menu == "Student Analytics":
        st.subheader("📊 Student Insights & Learning Gaps")
        if not roster:
            st.info("Add students in the Class Management tab to view their analytics.")
        else:
            # 1. Setup Student Lookup & Filters
            student_lookup = {}
            for s in roster:
                d = s.to_dict()
                student_lookup[s.id] = {
                    "name": d.get("display_name") or s.id.split("@")[0],
                    "grade": d.get("grade") or "Grade 6"
                }

            search_query = st.text_input("🔍 Search student by name...")
            all_grades = sorted(set(v["grade"] for v in student_lookup.values()))
            grade_filter = st.selectbox("Filter by Grade", ["All Grades"] + all_grades)
            time_filter = st.radio("Show interactions from", ["Last 12 Hours", "Last 24 Hours", "Last 3 Days", "Last 7 Days"], horizontal=True)
            
            tmap = {"Last 12 Hours": 43200, "Last 24 Hours": 86400, "Last 3 Days": 259200, "Last 7 Days": 604800}
            cutoff = time.time() - tmap[time_filter]

            filtered_students = {
                e: inf for e, inf in student_lookup.items()
                if (search_query.lower() in inf["name"].lower() or not search_query) and
                   (grade_filter == "All Grades" or inf["grade"] == grade_filter)
            }

            if not filtered_students:
                st.warning("No students match your search/filter.")
            else:
                disp_list = [f"{inf['name']} ({inf['grade']})" for inf in filtered_students.values()]
                e_list = list(filtered_students.keys())
                sel_idx = st.selectbox("Select Student", range(len(disp_list)), format_func=lambda i: disp_list[i])
                
                selected_student = e_list[sel_idx]
                selected_name = filtered_students[selected_student]["name"]

                st.markdown(f"### Report for **{selected_name}**")

                # 2. Get Subjects Taught
                my_classes_raw = list(db.collection("classes").where(filter=firestore.FieldFilter("created_by", "==", user_email)).stream())
                tsubjs = []
                for c in my_classes_raw:
                    if selected_student in c.to_dict().get("students", []):
                        tsubjs = c.to_dict().get("subjects", [])
                        break

                # 3. Data Processing Variables
                analytics_docs = db.collection("users").document(selected_student).collection("analytics").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(100).stream()
                
                recent_w = set()
                recent_q = []
                total_score = 0
                score_count = 0
                
                # New Dictionary to track Chapter Mastery
                chapter_stats = {}

                for doc in analytics_docs:
                    data = doc.to_dict()
                    if data.get("timestamp", 0) < cutoff:
                        continue
                        
                    doc_subject = data.get("subject", "General")
                    if tsubjs and doc_subject not in tsubjs:
                        continue
                        
                     score = data.get("score")
                    ch_num = data.get("chapter_number", 0)
                    ch_name = data.get("chapter_name", "General Concepts")
                    
                    if score is None:
                        continue 

                    
                    if isinstance(score, (int, float)):
                        total_score += score
                        score_count += 1
                        
                        # Accumulate scores per chapter
                        ch_key = f"{doc_subject} | Ch {ch_num}: {ch_name}" if ch_num > 0 else f"{doc_subject} | {ch_name}"
                        if ch_key not in chapter_stats:
                            chapter_stats[ch_key] = {"total": 0, "count": 0}
                        chapter_stats[ch_key]["total"] += score
                        chapter_stats[ch_key]["count"] += 1

                    wp = data.get("weak_point")
                    if wp and str(wp).lower() not in ["none", "null", ""]:
                        ch_display = f"Ch {ch_num}: {ch_name}" if ch_num > 0 else ch_name
                        recent_w.add(f"**{doc_subject} ({ch_display}):** {wp}")
                        
                    qa = data.get("question_asked")
                    if qa and str(qa).lower() not in ["none", "null", ""]:
                        recent_q.append(qa)

                # 4. Global Metrics
                health = int(total_score / score_count) if score_count > 0 else 0
                
                if score_count == 0 and not recent_q:
                    st.info(f"{selected_name} has no interactions in this subject/time range.")
                else:
                    if health >= 80: s_lbl = f"🟢 {health}% (Excellent)"
                    elif health >= 50: s_lbl = f"🟠 {health}% (Average)"
                    else: s_lbl = f"🔴 {health}% (Needs Help)"
                    
                    c1, c2, c3 = st.columns(3)
                    with c1: st.metric("Questions Asked", len(recent_q))
                    with c2: st.metric("Overall Concept Mastery", s_lbl)
                    with c3: st.metric("Data Points Analyzed", score_count)
                    
                    st.divider()

                    # 5. NEW: Chapter-by-Chapter Mastery UI
                    st.markdown("### 📚 Chapter Mastery Breakdown")
                    if chapter_stats:
                        for ch_key, stats in chapter_stats.items():
                            ch_avg = int(stats["total"] / stats["count"])
                            # Color coding based on score
                            if ch_avg >= 80: bar_color = "#2ecc71"  # Green
                            elif ch_avg >= 50: bar_color = "#f1c40f" # Yellow
                            else: bar_color = "#e74c3c"             # Red
                            
                            st.markdown(f"**{ch_key}** — {ch_avg}%")
                            st.markdown(
                                f"""
                                <div style="width: 100%; background-color: rgba(255,255,255,0.1); border-radius: 5px; margin-bottom: 15px;">
                                  <div style="width: {ch_avg}%; background-color: {bar_color}; height: 8px; border-radius: 5px;"></div>
                                </div>
                                """, unsafe_allow_html=True
                            )
                    else:
                        st.caption("Not enough data to calculate chapter mastery.")

                    st.divider()

                    # 6. Weak Points & Questions
                    c4, c5 = st.columns(2)
                    with c4:
                        st.markdown("#### 🚨 Identified Weak Points")
                        if recent_w:
                            for w in list(recent_w)[:7]: st.error(w)
                        else: st.success("No major weak points identified!")
                    with c5:
                        st.markdown("#### 💬 Recently Asked Questions")
                        if recent_q:
                            for q in recent_q[:5]: st.info(q)
                        else: st.write("No direct questions asked recently.")


    # ── MENU 3: ASSIGN PAPERS
    elif teacher_menu == "📝 Assign Papers":
        st.subheader("📝 Assignment Creator")
        st.markdown("#### Step 1: Configure Paper")
        a_col1, a_col2 = st.columns(2)
        with a_col1:
            assign_title = st.text_input("Assignment Title", placeholder="e.g. Chapter 4 Science Quiz")
            assign_subject = st.selectbox("Subject", ["Math", "Biology", "Chemistry", "Physics", "English"])
            assign_grade = st.selectbox("Grade", ["Grade 6", "Grade 7", "Grade 8"])
            assign_stage = GRADE_TO_STAGE[assign_grade] # Map to Stage for AI accuracy
        with a_col2:
            assign_difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard", "Mixed"])
            assign_marks = st.number_input("Total Marks", min_value=10, max_value=100, value=30, step=5)
            assign_due = st.date_input("Due Date")

        assign_extra = st.text_area("Additional Instructions (optional)", height=80)
        
        PAPER_SYSTEM = """
        You generate formal school question papers.
        - Plain text math (no LaTeX).
        - Clean numbering, marks like [3].
        - Include '## Mark Scheme' at the end.
        - Append [PDF_READY] at the end.
        - Do not hallucinate adding school names or any of that. Just use the assignment title as the title of the paper.
        """

        if st.button("🤖 Generate with Helix AI", use_container_width=True, type="primary"):
            if "textbook_handles" not in st.session_state:
                st.session_state.textbook_handles = upload_textbooks()
                
            with st.spinner(f"Reading {assign_grade} {assign_subject} curriculum and writing paper..."):
                try:
                    query_for_books = f"{assign_subject} {assign_grade}"
                    relevant_books = select_relevant_books(query_for_books, st.session_state.textbook_handles)
                    
                    paper_contents = []
                    for book in relevant_books:
                        friendly = get_friendly_name(book.display_name)
                        paper_contents.append(types.Part.from_text(text=f"[Curriculum Source: {friendly}]"))
                        paper_contents.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))
                        
                    gen_prompt = (
                        f"Using ONLY the provided Cambridge textbooks, generate a formal CIE {assign_subject} question paper "
                        f"for {assign_stage} ({assign_grade}) students. \n"
                        f"Difficulty: {assign_difficulty}. Total marks: {assign_marks}. \n"
                        f"Instructions: {assign_extra if assign_extra else 'None'}. \n"
                        f"Do NOT invent topics outside this syllabus. Append [PDF_READY] at the end."
                    )
                    paper_contents.append(types.Part.from_text(text=gen_prompt))

                    gen_resp = client.models.generate_content(
                        model="gemini-2.5-pro",
                        contents=paper_contents,
                        config=types.GenerateContentConfig(
                            system_instruction=PAPER_SYSTEM, 
                            temperature=0.1, 
                            max_output_tokens=8000
                        ),
                    )
                    
                    gen_paper = safe_response_text(gen_resp).strip()
                    st.session_state["draft_paper"] = gen_paper
                    st.session_state["draft_title"] = assign_title or f"{assign_subject} {assign_grade} Paper"
                    st.session_state["draft_due"] = str(assign_due)
                    st.rerun()
                except Exception as e: st.error(f"Generation failed: {e}")

        if st.session_state.get("draft_paper"):
            with st.expander("👁️ Preview Paper", expanded=True):
                st.markdown(st.session_state["draft_paper"].replace("[PDF_READY]", "").strip())
            
            try:
                pdf_buf = create_pdf(st.session_state["draft_paper"])
                st.download_button(label="📥 Download Paper as PDF", data=pdf_buf, file_name=f"{st.session_state['draft_title']}.pdf", mime="application/pdf")
            except Exception: pass

            st.divider()
            push_mode = st.radio("Push to:", ["Entire Class", "Individual Student"], horizontal=True)
            my_classes_raw = list(db.collection("classes").where(filter=firestore.FieldFilter("created_by", "==", user_email)).stream())
            if push_mode == "Entire Class":
                class_options = {c.id: c.to_dict().get("students", []) for c in my_classes_raw}
                if not class_options: st.warning("You haven't created any classes yet.")
                else:
                    target_class = st.selectbox("Select Class:", list(class_options.keys()))
                    if st.button(f"🚀 Push to {target_class}", use_container_width=True, type="primary"):
                        for s_email in class_options[target_class]:
                            try: db.collection("users").document(s_email).collection("assignments").add({"title": st.session_state["draft_title"], "content": st.session_state["draft_paper"], "assigned_by": user_email, "assigned_at": time.time(), "due_date": st.session_state["draft_due"], "status": "pending", "class": target_class})
                            except Exception: pass
                        st.success(f"✅ Pushed to {target_class}!"); del st.session_state["draft_paper"]; time.sleep(1); st.rerun()
            else:
                if not roster: st.warning("No students in your roster.")
                else:
                    target_email = st.selectbox("Select Student:", [s.id for s in roster], format_func=lambda e: db.collection("users").document(e).get().to_dict().get("display_name", e.split("@")[0]))
                    if st.button(f"🚀 Push to Student", use_container_width=True, type="primary"):
                        db.collection("users").document(target_email).collection("assignments").add({"title": st.session_state["draft_title"], "content": st.session_state["draft_paper"], "assigned_by": user_email, "assigned_at": time.time(), "due_date": st.session_state["draft_due"], "status": "pending", "class": "Individual"})
                        st.success("✅ Pushed!"); del st.session_state["draft_paper"]; time.sleep(1); st.rerun()

            if st.button("🗑️ Discard Draft", use_container_width=True): del st.session_state["draft_paper"]; st.rerun()

    # ── MENU 4: AI CHAT
    elif teacher_menu == "💬 AI Chat":
        st.info("💡 You are chatting with Helix as a Teacher. History is saved to your sidebar.")
        render_chat_interface = True 

else:
    # Student / Guest view always gets the chat interface
    render_chat_interface = True
    st.markdown("<div class='big-title'>📚 helix.ai</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>Your CIE Tutor for Grade 6-8!</div>", unsafe_allow_html=True)

    if is_authenticated and user_role == "student":
        student_class = get_student_class_data(user_email)
        
        if student_class and "grade" in student_class:
            class_grade = student_class["grade"]
            if user_profile.get("grade") != class_grade:
                db.collection("users").document(user_email).update({"grade": class_grade})
                user_profile["grade"] = class_grade
        else:
            current_grade = user_profile.get("grade", "Grade 6")
            GRADE_OPTIONS = ["Grade 6", "Grade 7", "Grade 8"]
            with st.expander("🎓 Set Your Grade", expanded=(current_grade not in GRADE_OPTIONS)):
                selected_grade = st.selectbox(
                    "Which grade are you in?", 
                    options=GRADE_OPTIONS, 
                    index=GRADE_OPTIONS.index(current_grade) if current_grade in GRADE_OPTIONS else 0
                )
                if st.button("Save Grade"):
                    db.collection("users").document(user_email).update({"grade": selected_grade})
                    st.success(f"Grade set to {selected_grade}!")
                    time.sleep(0.8)
                    st.rerun()

# ==========================================
# UNIVERSAL CHAT VIEW (Only renders if allowed)
# ==========================================
if render_chat_interface:
    
    SYSTEM_INSTRUCTION = """
    You are Helix, a friendly CIE Science/Math/English Tutor for Grade 6-8 students.

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
    - PLAIN TEXT MATH ONLY: Use standard characters (/, x, *, ÷, ^,-,+,=).
    - Tables: ALWAYS use standard Markdown tables. Do NOT use IMAGE_GEN for tables.
    - Visuals: Use IMAGE_GEN for diagrams, PIE_CHART for pie charts.
    - NUMBERING: Clean numbering 1., 2., 3. and always atleast 2-3 sub-questions (a), (b), (c).
    - MARKS: Put marks at end of the SAME LINE like "... [3]".
    - When you are asked to create a question paper, the assignment title must be the TITLE of the paper. You should not use any other made-up name for the title. Do not hallucinate while creating the name of the paper. Do not mention the SCHOOL name either. Just mention the grade and the chapter this test is made for .
    - PDF TRIGGER: If, and ONLY IF, you generated a full formal question paper, append [PDF_READY] at the very end.

    ### RULE 4: English, Grade 8/Stage 9:
    I could not find the book for stage 9/grade 8, so here is the syllabus:
    Chapter 1 • Writing to explore and reflect
1.1 What is travel writing?

1.2 Selecting and noting key information in travel texts

1.3 Comparing tone and register in travel texts

1.4 Responding to travel writing

1.5 Understanding grammatical choices in travel writing

1.6 Varying sentences for effect

1.7 Boost your vocabulary

1.8 Creating a travel account

Chapter 2 • Writing to inform and explain
2.1 Matching informative texts to audience and purpose

2.2 Using formal and informal language in information texts

2.3 Comparing information texts

2.4 Using discussion to prepare for a written assignment

2.5 Planning information texts to suit different audiences

2.6 Shaping paragraphs to suit audience and purpose

2.7 Crafting sentences for a range of effects

2.8 Making explanations precise and concise

2.9 Writing encyclopedia entries

Chapter 3 • Writing to argue and persuade
3.1 Reviewing persuasive techniques

3.2 Commenting on use of language to persuade

3.3 Exploring layers of persuasive language

3.4 Responding to the use of persuasive language

3.5 Adapting grammar choices to create effects in argument writing

3.6 Organising a whole argument effectively

3.7 Organising an argument within each paragraph

3.8 Presenting and responding to a question

3.9 Producing an argumentative essay

Chapter 4 • Descriptive writing
4.1 Analysing how atmospheres are created

4.2 Developing analysis of a description

4.3 Analysing atmospheric descriptions

4.4 Using images to inspire description

4.5 Using language to develop an atmosphere

4.6 Sustaining a cohesive atmosphere

4.7 Creating atmosphere through punctuation

4.8 Using structural devices to build up atmosphere

4.9 Producing a powerful description

Chapter 5 • Narrative writing
5.1 Understanding story openings

5.2 Exploring setting and atmosphere

5.3 Introducing characters in stories

5.4 Responding to powerful narrative

5.5 Pitching a story

5.6 Creating narrative suspense and climax

5.7 Creating character

5.8 Using tenses in narrative

5.9 Using pronouns and sentence order for effect

5.10 Creating a thriller

Chapter 6 • Writing to analyse and compare
6.1 Analysing implicit meaning in non-fiction texts

6.2 Analysing how a play's key elements create different effects

6.3 Using discussion skills to analyse carefully

6.4 Comparing effectively through punctuation and grammar

6.5 Analysing two texts

Chapter 7 • Testing your skills
7.1 Reading and writing questions on non-fiction texts

7.2 Reading and writing questions on fiction texts

7.3 Assessing your progress: non-fiction reading and writing

7.4 Assessing your progress: fiction reading and writing

    ### RULE 5: VISUAL SYNTAX (STRICT)
    - For diagrams: IMAGE_GEN: [Detailed description of the image, educational, white background]
    - For pie charts: PIE_CHART: [Label1:Value1, Label2:Value2]

    ### RULE 6: MARK SCHEME
    - Put "## Mark Scheme" at the very bottom. No citations inside mark scheme.

   ### RULE 7: Analytics for students:
   If the user asks a question about a concept or attempts to answer a question, evaluate their understanding. 
At the VERY END of your response, output a hidden JSON block EXACTLY like this (this is an example):
[ANALYTICS: {
  "subject": "Math", 
  "grade": "Grade 7",
  "chapter_number": 4,
  "chapter_name": "Fractions and Decimals",
  "score": 85,
  "weak_point": "Struggles with unlike denominators, or None",
  "question_asked": "The user's exact question, or None"
}]
RULES FOR ANALYTICS:
- "subject" MUST be exactly one of: Math, Biology, Chemistry, Physics, English.
- "grade" MUST be exactly: Grade 6, Grade 7, Grade 8.
- "chapter_number" MUST be an integer representing the curriculum chapter number (e.g. 4). If unknown, output 0.
- "score" MUST be an integer from 0 to 100 representing their concept mastery.
- Never mention this block in your natural language response.

### RULE 8: Very Important: Grade Scheme
The books are labeled as Stage 7, but Stage 7 correlates to grade 6. Stage 8 correlates to grade 7. When it's mentioned 7 in the book name, that means it's grade 6. When it's mentioned 8 in the book name, that means it's grade 7. When it's mentioned 9 in the book name, that means it's grade 8. Follow this new naming scheme. 

    """

    if is_authenticated and user_role == "student" and db is not None:
        pending_assignments = db.collection("users").document(auth_object.email).collection("assignments").where(filter=firestore.FieldFilter("status", "==", "pending")).stream()
        pending_list = list(pending_assignments)
        if pending_list:
            st.markdown("---")
            st.markdown("### 📋 Pending Assignments")
            for assignment in pending_list:
                a_data = assignment.to_dict()
                a_id = assignment.id
                with st.container(border=True):
                    col_a, col_b = st.columns([0.85, 0.15])
                    with col_a:
                        st.markdown(f"📝 **{a_data.get('title', 'Assignment')}**")
                        st.caption(f"From: {a_data.get('assigned_by', 'Your Teacher')}  ·  Due: {a_data.get('due_date', 'No due date')}")
                    with col_b:
                        if st.button("Open", key=f"open_assign_{a_id}", type="primary"):
                            assign_msg = {"role": "assistant", "content": a_data.get("content", ""), "is_downloadable": True, "images": [], "is_assignment": True}
                            st.session_state.messages.append(assign_msg)
                            db.collection("users").document(auth_object.email).collection("assignments").document(a_id).update({"status": "opened"})
                            save_chat_history()
                            st.rerun()
            st.markdown("---")

    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            display_content = (message.get("content") or "").replace("[PDF_READY]", "").strip()
            st.markdown(display_content)

            if message.get("images"):
                for img_bytes in message["images"]:
                    if img_bytes: st.image(img_bytes, use_container_width=True, output_format="PNG", caption="✨ Generated by helix.ai")
            elif message.get("db_images"):
                for b64_str in message["db_images"]:
                    if b64_str:
                        try:
                            img_bytes = base64.b64decode(b64_str)
                            st.image(img_bytes, use_container_width=True, output_format="JPEG", caption="✨ Generated by helix.ai")
                        except Exception: pass

            if message.get("user_attachment_bytes"):
                mime = message.get("user_attachment_mime", "")
                name = message.get("user_attachment_name", "File")
                if "image" in mime: st.image(message["user_attachment_bytes"], width=320)
                elif "pdf" in mime: st.caption(f"📄 *Attached PDF Document: {name}*")
                elif "text" in mime or name.endswith(".txt"): st.caption(f"📝 *Attached Text Document: {name}*")

            if message["role"] == "assistant" and message.get("is_downloadable"):
                try:
                    pdf_buffer = create_pdf(message.get("content") or "", images=message.get("images", []))
                    st.download_button(label="📥 Download Question Paper as PDF", data=pdf_buffer, file_name=f"Helix_Question_Paper_{idx}.pdf", mime="application/pdf", key=f"download_{st.session_state.current_thread_id}_{idx}")
                except Exception: pass

    chat_input_data = st.chat_input("Ask Helix... (Click the paperclip to upload a file!)", accept_file=True, file_type=["jpg", "jpeg", "png", "webp", "avif", "svg", "pdf", "txt"])

    if chat_input_data:
        if "textbook_handles" not in st.session_state:
            st.session_state.textbook_handles = upload_textbooks()

        prompt = chat_input_data.text or ""
        uploaded_files = chat_input_data.files
        user_msg = {"role": "user", "content": prompt}
        file_bytes, file_mime, file_name = None, None, None

        if uploaded_files and len(uploaded_files) > 0:
            uf = uploaded_files[0]
            file_bytes = uf.getvalue(); file_mime = uf.type; file_name = uf.name
            user_msg["user_attachment_bytes"] = file_bytes
            user_msg["user_attachment_mime"] = file_mime
            user_msg["user_attachment_name"] = file_name

        st.session_state.messages.append(user_msg)
        save_chat_history()

        with st.chat_message("user"):
            st.markdown(prompt)
            if file_bytes:
                if "image" in (file_mime or ""): st.image(file_bytes, width=320)
                elif "pdf" in (file_mime or ""): st.caption(f"📄 *Attached: {file_name}*")
                elif "text/plain" in (file_mime or "") or (file_name or "").endswith(".txt"): st.caption(f"📝 *Attached: {file_name}*")

        with st.chat_message("assistant"):
            thinking_placeholder = st.empty()
            try:
                has_attachment = file_bytes is not None
                relevant_books = select_relevant_books(prompt + " science stage 8" if has_attachment else prompt, st.session_state.textbook_handles)


                thinking_placeholder.markdown("""<div class="thinking-container"><span class="thinking-text">Thinking</span><div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div></div>""", unsafe_allow_html=True)

                current_prompt_parts = []
                temp_pdf_path = None

                if file_bytes:
                    if "image" in (file_mime or ""): current_prompt_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime))
                    elif "pdf" in (file_mime or ""):
                        temp_pdf_path = f"temp_user_upload_{int(time.time())}.pdf"
                        with open(temp_pdf_path, "wb") as f: f.write(file_bytes)
                        user_uploaded_pdf = client.files.upload(file=temp_pdf_path)
                        while user_uploaded_pdf.state.name == "PROCESSING":
                            time.sleep(1)
                            user_uploaded_pdf = client.files.get(name=user_uploaded_pdf.name)
                        current_prompt_parts.append(types.Part.from_uri(file_uri=user_uploaded_pdf.uri, mime_type="application/pdf"))
                    elif "text/plain" in (file_mime or "") or (file_name or "").endswith(".txt"):
                        raw_text = file_bytes.decode("utf-8", errors="ignore")
                        current_prompt_parts.append(types.Part.from_text(text=f"--- Attached Text File ({file_name}) ---\n{raw_text}\n--- End of File ---\n"))

                for book in relevant_books:
                    friendly = get_friendly_name(book.display_name)
                    current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly}]"))
                    current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))

                current_prompt_parts.append(types.Part.from_text(text=f"Please read the user query and look at attached files. Check Cambridge textbooks for accuracy if provided.\n\nQuery: {prompt}"))
                current_content = types.Content(role="user", parts=current_prompt_parts)

                history_contents = []
                text_msgs = [m for m in st.session_state.messages[:-1] if not m.get("is_greeting")]
                for msg in text_msgs[-7:]:
                    role = "user" if msg["role"] == "user" else "model"
                    history_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content") or "")]))

                full_contents = history_contents + [current_content]

                text_response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=full_contents,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.3, tools=[{"google_search": {}}]),
                )

                bot_text = safe_response_text(text_response)
                if not bot_text.strip(): bot_text = "⚠️ *Helix couldn't generate a text response this time.* Try rephrasing your question."

                analytics_match = re.search(r"\[ANALYTICS:\s*({.*?})\s*\]", bot_text, flags=re.IGNORECASE | re.DOTALL)
                if analytics_match:
                    try:
                        analytics_data = json.loads(analytics_match.group(1))
                        bot_text = bot_text[:analytics_match.start()].strip()
                        if is_authenticated and db is not None:
                            db.collection("users").document(auth_object.email).collection("analytics").add({
                                "timestamp": time.time(),
                                "subject": analytics_data.get("subject", "General"),
                                "grade": analytics_data.get("grade", "Unknown"),
                                "chapter_number": int(analytics_data.get("chapter_number", 0)),
                                "chapter_name": analytics_data.get("chapter_name", "General"),
                                "score": int(analytics_data.get("score", 50)),
                                "weak_point": analytics_data.get("weak_point", "None"),
                                "question_asked": analytics_data.get("question_asked", "None")
                            })
                            
                    except Exception as e: print(f"Analytics extraction error: {e}")

                thinking_placeholder.empty()

                visual_prompts = re.findall(r"(IMAGE_GEN|PIE_CHART):\s*\[(.*?)\]", bot_text)
                generated_images = []

                if visual_prompts:
                    img_thinking = st.empty()
                    img_thinking.markdown("""<div class="thinking-container"><span class="thinking-text">🖌️ Processing diagrams & charts...</span><div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div></div>""", unsafe_allow_html=True)
                    def process_visual_wrapper(vp):
                        try:
                            v_type, v_data = vp
                            if v_type == "IMAGE_GEN":
                                try:
                                    img_resp = client.models.generate_content(
                                        model="gemini-3.1-flash-image-preview",
                                        contents=[v_data],
                                        config=types.GenerateContentConfig(
                                            response_modalities=["TEXT", "IMAGE"],
                                            image_config=types.ImageConfig(aspect_ratio="16:9", image_size="2K")
                                        ),
                                    )
                                    for part in (img_resp.parts or []):
                                        if getattr(part, "inline_data", None):
                                            return part.inline_data.data
                                except: return None
                            elif v_type == "PIE_CHART":
                                try:
                                    labels, sizes = [], []
                                    for item in str(v_data).split(","):
                                        if ":" in item:
                                            k, v = item.split(":", 1)
                                            labels.append(k.strip())
                                            sizes.append(float(re.sub(r"[^\d\.]", "", v)))
                                    if not labels or not sizes or len(labels) != len(sizes): return None
                                    fig = Figure(figsize=(5, 5), dpi=200)
                                    FigureCanvas(fig)
                                    ax = fig.add_subplot(111)
                                    theme_colors = ["#00d4ff", "#fc8404", "#2ecc71", "#9b59b6", "#f1c40f", "#e74c3c"]
                                    ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140, colors=theme_colors[:len(labels)], textprops={"color": "black", "fontsize": 9})
                                    ax.axis("equal")
                                    buf = BytesIO()
                                    fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
                                    return buf.getvalue()
                                except: return None
                        except: return None

                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        generated_images = list(executor.map(process_visual_wrapper, visual_prompts))
                    img_thinking.empty()
                    for img in generated_images:
                        if img is None: bot_text += "\n\n⚠️ *Helix tried to draw a diagram here, but the image generator is currently overloaded. Please try again later.*"

                is_downloadable = ("[PDF_READY]" in bot_text or ("## Mark Scheme" in bot_text and re.search(r"\[\d+\]", bot_text) is not None))

                bot_msg = {"role": "assistant", "content": bot_text, "is_downloadable": is_downloadable, "images": generated_images}
                st.session_state.messages.append(bot_msg)

                if is_authenticated:
                    user_msg_count = sum(1 for m in st.session_state.messages if m.get("role") == "user")
                    if user_msg_count == 1:
                        coll_ref = get_threads_collection()
                        if coll_ref and st.session_state.current_thread_id:
                            thread_doc = coll_ref.document(st.session_state.current_thread_id).get()
                            user_edited = thread_doc.to_dict().get("user_edited_title", False) if thread_doc.exists else False
                            if not user_edited:
                                new_title = generate_chat_title(client, st.session_state.messages)
                                if new_title and new_title != "New Chat":
                                    coll_ref.document(st.session_state.current_thread_id).set({"title": new_title}, merge=True)

                save_chat_history()
                st.rerun()

            except Exception as e:
                thinking_placeholder.empty()
                st.error(f"Helix Error: {e}")
            finally:
                try:
                    if "temp_pdf_path" in locals() and temp_pdf_path and os.path.exists(temp_pdf_path): os.remove(temp_pdf_path)
                except Exception: pass

