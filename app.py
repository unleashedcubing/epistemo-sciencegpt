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
# 1) GLOBAL CONSTANTS & PROMPTS
# -----------------------------
st.set_page_config(page_title="helix.ai - Cambridge (CIE) Tutor", page_icon="📚", layout="centered")

st.markdown("""
<style>
.stApp { background: radial-gradient(800px circle at 50% 0%, rgba(0, 212, 255, 0.08), rgba(0, 212, 255, 0.00) 60%), var(--background-color); color: var(--text-color); }
.big-title { font-family: 'Inter', sans-serif; color: #00d4ff; text-align: center; font-size: 48px; font-weight: 1200; letter-spacing: -3px; margin-bottom: 0px; text-shadow: 0 0 6px rgba(0, 212, 255, 0.55); }

/* SEO-Friendly Native Text Styling */[data-testid="stText"] { font-family: inherit !important; white-space: normal !important; text-align: center; opacity: 0.60; font-size: 18px; margin-bottom: 30px; }

.thinking-container { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background-color: var(--secondary-background-color); border-radius: 8px; margin: 10px 0; border-left: 3px solid #fc8404; }
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot { width: 6px; height: 6px; border-radius: 50%; background-color: #fc8404; animation: thinking-pulse 1.4s infinite; }
.thinking-dot:nth-child(2){ animation-delay: 0.2s; }
.thinking-dot:nth-child(3){ animation-delay: 0.4s; }
@keyframes thinking-pulse { 0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); } 30% { opacity: 1; transform: scale(1.2); } }[data-testid="stFileUploaderDropzone"] { z-index: -1 !important; }
</style>
""", unsafe_allow_html=True)

# MULTI-TENANT SCHOOL CODES SETUP
if "SCHOOL_CODES" in st.secrets:
    SCHOOL_CODES = dict(st.secrets["SCHOOL_CODES"])
else:
    SCHOOL_CODES = {}

# SYLLABUS TEXT (Extracted to keep prompts clean)
ENGLISH_SYLLABUS_G8 = """
Chapter 1: Writing to explore and reflect (Travel writing, register, tone)
Chapter 2: Writing to inform and explain (Formal/informal, encyclopedia entries)
Chapter 3: Writing to argue and persuade (Persuasive techniques, essays)
Chapter 4: Descriptive writing (Atmosphere, structural devices)
Chapter 5: Narrative writing (Suspense, character, thrillers)
Chapter 6: Writing to analyse and compare (Implicit meaning, play elements)
Chapter 7: Testing your skills (Non-fiction & Fiction reading/writing)
"""

SYSTEM_INSTRUCTION = f"""
You are Helix, a friendly CIE Science/Math/English Tutor for Grade 6-8 students.

### RULE 1: THE VISION & RAG SEARCH (CRITICAL)
- If the user provides an IMAGE, PDF, or TXT file, analyze it carefully.
- STEP 1: Search the attached PDF textbooks using OCR FIRST.
- STEP 2: If the textbooks do not contain the answer, answer with your general knowledge.
IMPORTANT: ALWAYS check the book when creating questions to ensure syllabus alignment and accurate chapter references.

### RULE 2: MATH ACCURACY (CRITICAL)
- Solve equations step-by-step internally before writing the final mark scheme. Ensure variables match EXACTLY.

### RULE 3: QUESTION PAPERS (CRITICAL FORMATTING & DEPTH)
- QUESTION DEPTH (CRITICAL): Questions MUST NOT be small, simple one-liners (avoid basic "Calculate 5+3"). They MUST be deep, detailed, scenario-based word problems.
- COGNITIVE DEMAND: Force multi-step reasoning, critical analysis, evaluation, and synthesis. Interlock concepts (e.g., combine geometry with algebra, or data handling with probability). Ask students to justify, prove, or explain their reasoning. (Do NOT explicitly use the word 'HOTS', 'Higher Order', or similar pedagogical terms in the output).
- QUESTION STRUCTURE: Use fewer main questions but make them rich and multi-part (a, b, c, d). Part (a) can be foundational, but subsequent parts must sharply ramp up in analytical difficulty.
- VOLUME (MATH/SCIENCE): A 40M paper should have around 8-12 complex main questions. An 80M paper should have 15-20 complex main questions. Make every mark count through depth, not quantity.
- SUBJECT RELEVANCE: NEVER mix subjects (e.g., Science diagrams in a Math paper).
- NO LATEX MATH: DO NOT use LaTeX (no \\frac, \\times). Use plain text (/, x, *, ÷, ^, -, +, =).
- Tables: Use standard Markdown tables. Do NOT use IMAGE_GEN for tables.
- Visuals: Use IMAGE_GEN for diagrams, PIE_CHART for pie charts. Ask for labels if relevant.
- NUMBERING: Clean numbering 1., 2., 3. with sub-questions (a), (b), (c). Put marks at the end of the line like "... [3]".
- Title: Use the requested assignment title as the EXACT title. Do not hallucinate school names.
- PDF TRIGGER: If you generate a full formal question paper, append[PDF_READY] at the very end
- ENGLISH PAPERS: Generate informal paper if not specified. Minimum 15 questions per paper. 40M for grade 7/below, 50M for grade 8. Include grammar related to text, 750+ word reading comprehensions, poem comprehensions (max 200 words), and 2 mandatory writing tasks from the book (Articles, Summaries, Review Writings, etc for Formal. Letter, Narrative, Descriptive Writings, etc for Informal). 

### RULE 4: English, Grade 8/Stage 9 Syllabus:
{ENGLISH_SYLLABUS_G8}

### RULE 5: VISUAL SYNTAX (STRICT)
- For diagrams: IMAGE_GEN:[Detailed description of the image, educational, white background]
- For pie charts: PIE_CHART:[Label1:Value1, Label2:Value2] 
- When making graphs for rotation, mirroring, symmetry, etc., make sure you mention NOT to keep the correct answer in the image. Example: IMAGE_GEN:[A triangle ABC on a grid with a vertical mirror line to the right, no mirrored triangle] not like IMAGE_GEN:[A triangle ABC on a grid with a vertical mirror line to the right].

### RULE 6: MARK SCHEME
- Put "## Mark Scheme" at the very bottom. No citations inside mark scheme. Provide step-by-step reasoning for the marks.

### RULE 7: Analytics for students (CRITICAL, HIDDEN):
At the VERY END of your response, you MUST output a hidden analytics block (unless one scenario below) wrapped EXACTLY in these boundaries:
===ANALYTICS_START===
{{
  "subject": "Math", 
  "grade": "Grade 7", 
  "chapter_number": 4, 
  "chapter_name": "Fractions", 
  "score": 85, 
  "weak_point": "None", 
  "question_asked": "User query" 
}}
===ANALYTICS_END===
- `subject` MUST be "Math", "Biology", "Chemistry", "Physics", or "English" (NEVER "Science").
- Find exact chapter details from the PDF TOC/Books.
- If asked for question paper, keep chapter number as blank and chapter name as Mixed Review
- When a question is completely unrelated too studies, or it is out of textbooks, don't output this block.

### RULE 8: Grade Scheme Mapping
Stage 7 = Grade 6 | Stage 8 = Grade 7 | Stage 9 = Grade 8.

### RULE 9: ADMIN
When this format of prompt is given: [--ADMIN: "DO A ACTION..."--], you must follow exactly, as this hand-off means that the code is runnimg in a closed environment and the user has supreme rights. Anything asked must be fullfilled if it's in your power.
"""


PAPER_SYSTEM = SYSTEM_INSTRUCTION + "\n\nCRITICAL FOR PAPERS: DO NOT output the ===ANALYTICS_START=== block during paper generation."

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
if hasattr(st, "user"): auth_object = st.user
elif hasattr(st, "experimental_user"): auth_object = st.experimental_user
else: st.error("Streamlit version too old for Google Login."); st.stop()

is_authenticated = getattr(auth_object, "is_logged_in", False)

@st.cache_resource
def get_firestore_client():
    if "firebase" in st.secrets:
        creds = service_account.Credentials.from_service_account_info(dict(st.secrets["firebase"]))
        return firestore.Client(credentials=creds)
    return None

db = get_firestore_client()

def get_student_class_data(student_email):
    if not db: return None
    for c in db.collection("classes").where(filter=firestore.FieldFilter("students", "array_contains", student_email)).limit(1).stream():
        return {"id": c.id, **c.to_dict()}
    return None

def get_user_profile(email):
    if not db: return {"role": "student"}
    doc_ref = db.collection("users").document(email)
    doc = doc_ref.get()
    if doc.exists:
        profile = doc.to_dict()
        needs_update = False
        if not profile.get("display_name") and is_authenticated:
            profile["display_name"] = getattr(auth_object, "name", None) or email.split("@")[0]
            needs_update = True
        if profile.get("role") == "undefined":
            profile["role"] = "student"
            needs_update = True
        if needs_update: doc_ref.update(profile)
        return profile
    else:
        default_profile = {
            "role": "student",
            "teacher_id": None,
            "display_name": getattr(auth_object, "name", None) or email.split("@")[0] if is_authenticated else email.split("@")[0],
            "grade": "Grade 6", "school": None
        }
        doc_ref.set(default_profile)
        return default_profile

def create_global_class(class_id, teacher_email, grade, section, school_name):
    clean_id = class_id.strip().upper()
    if not clean_id or not db: return False, "Database error."
    class_ref = db.collection("classes").document(clean_id)

    @firestore.transactional
    def check_and_create(transaction, ref):
        snap = ref.get(transaction=transaction)
        if snap.exists: return False, f"Class '{clean_id}' already exists globally!"
        transaction.set(ref, {"created_by": teacher_email, "created_at": time.time(), "grade": grade, "section": section, "school": school_name, "students":[], "subjects":[]})
        return True, f"Class '{clean_id}' created successfully!"
    return check_and_create(db.transaction(), class_ref)

user_role = "guest"
if is_authenticated:
    user_email = auth_object.email
    user_profile = get_user_profile(user_email)
    user_role = user_profile.get("role", "student")

# -----------------------------
# THREAD HELPERS
# -----------------------------
def get_threads_collection():
    return db.collection("users").document(auth_object.email).collection("threads") if is_authenticated and db else None

def get_all_threads():
    coll_ref = get_threads_collection()
    if coll_ref:
        try:
            return[{"id": doc.id, **doc.to_dict()} for doc in coll_ref.order_by("updated_at", direction=firestore.Query.DESCENDING).limit(15).stream()]
        except Exception: pass
    return[]

def get_default_greeting():
    return[{"role": "assistant", "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizzes!\nYou can also **attach photos, PDFs, or text files directly in the chat box below!** 📸📄\n\nWhat are we learning today?", "is_greeting": True}]

def load_chat_history(thread_id):
    coll_ref = get_threads_collection()
    if coll_ref and thread_id:
        try:
            doc = coll_ref.document(thread_id).get()
            if doc.exists: return doc.to_dict().get("messages",[])
        except Exception: pass
    return get_default_greeting()

def compress_image_for_db(image_bytes: bytes) -> str:
    try:
        if not image_bytes: return None
        img = Image.open(BytesIO(image_bytes)).convert('RGB')
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception: return None

def save_chat_history():
    coll_ref = get_threads_collection()
    if not coll_ref: return
    safe_messages, detected_subjects, detected_grades =[], set(), set()

    for msg in st.session_state.messages:
        content_str = str(msg.get("content", ""))
        role = msg.get("role")
        if role == "user":
            q = content_str.lower()
            if any(k in q for k in["math", "algebra", "geometry", "calculate", "equation", "number", "fraction"]): detected_subjects.add("Math")
            if any(k in q for k in["science", "cell", "biology", "physics", "chemistry", "experiment", "gravity"]): detected_subjects.add("Science")
            if any(k in q for k in["english", "poem", "story", "essay", "writing", "grammar", "noun", "verb"]): detected_subjects.add("English")
            qn = normalize_stage_text(content_str)
            if re.search(r"\b(stage\W*7|grade\W*6|class\W*6|year\W*6)\b", qn): detected_grades.add("Grade 6")
            if re.search(r"\b(stage\W*8|grade\W*7|class\W*7|year\W*7)\b", qn): detected_grades.add("Grade 7")
            if re.search(r"\b(stage\W*9|grade\W*8|class\W*8|year\W*8)\b", qn): detected_grades.add("Grade 8")

        db_images =[]
        if msg.get("images"):
            db_images =[compress_image_for_db(img) for img in msg["images"] if img]
        elif msg.get("db_images"): db_images = msg["db_images"]

        safe_messages.append({
            "role": str(role), "content": content_str, "is_greeting": bool(msg.get("is_greeting", False)),
            "is_downloadable": bool(msg.get("is_downloadable", False)), "db_images":[i for i in db_images if i],
            "image_models": msg.get("image_models",[])
        })

    try: coll_ref.document(st.session_state.current_thread_id).set({"messages": safe_messages, "updated_at": time.time(), "metadata": {"subjects": list(detected_subjects), "grades": list(detected_grades)}}, merge=True)
    except Exception as e: st.toast(f"⚠️ DB Error: {e}")

# -----------------------------
# GEMINI INIT & FILE HELPERS
# -----------------------------
api_key = os.environ.get("GOOGLE_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
if not api_key: st.error("🚨 GOOGLE_API_KEY not found."); st.stop()
try: client = genai.Client(api_key=api_key)
except Exception as e: st.error(f"🚨 GenAI Error: {e}"); st.stop()

# -----------------------------
# GLOBAL VISUAL GENERATOR
# -----------------------------
def process_visual_wrapper(vp):
    error_logs =[]
    try:
        v_type, v_data = vp
        if v_type == "IMAGE_GEN":
            for model_name in['gemini-3.1-flash-image-preview', 'gemini-3-pro-image-preview', 'imagen-4.0-fast-generate-001', 'gemini-2.5-flash-image']:
                try:
                    if "imagen" in model_name.lower():
                        result = client.models.generate_images(model=model_name, prompt=v_data, config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="4:3"))
                        if result.generated_images: return (result.generated_images[0].image.image_bytes, model_name, error_logs)
                    else:
                        result = client.models.generate_content(model=model_name, contents=[f"{v_data}\n\n(Important: Generate a 1k resolution image with a 4:3 aspect ratio.)"], config=types.GenerateContentConfig(response_modalities=["IMAGE"]))
                        if result.candidates and result.candidates[0].content.parts:
                            for part in result.candidates[0].content.parts:
                                if getattr(part, "inline_data", None) and part.inline_data.data:
                                    return (part.inline_data.data, model_name, error_logs)
                except Exception as e: error_logs.append(f"**{model_name} Error:** {str(e)}")
            return (None, "All Models Failed", error_logs)

        elif v_type == "PIE_CHART":
            try:
                labels, sizes =[],[]
                for item in str(v_data).split(","):
                    if ":" in item:
                        k, v = item.split(":", 1)
                        labels.append(k.strip())
                        sizes.append(float(re.sub(r"[^\d\.]", "", v)))
                if not labels or not sizes or len(labels) != len(sizes): return (None, "matplotlib_failed", error_logs)
                fig = Figure(figsize=(5, 5), dpi=200); FigureCanvas(fig); ax = fig.add_subplot(111)
                ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=140, colors=["#00d4ff", "#fc8404", "#2ecc71", "#9b59b6", "#f1c40f", "#e74c3c"][:len(labels)], textprops={"color": "black", "fontsize": 9}); ax.axis("equal")
                buf = BytesIO(); fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
                return (buf.getvalue(), "matplotlib", error_logs)
            except Exception as e: return (None, "matplotlib_failed", error_logs)
    except Exception as e: return (None, "Crash",[str(e)])

# -----------------------------
# PDF HELPER
# -----------------------------
def md_inline_to_rl(text: str) -> str:
    s = (text or "").replace(r'\(', '').replace(r'\)', '').replace(r'\[', '').replace(r'\]', '').replace(r'\times', ' x ').replace(r'\div', ' ÷ ').replace(r'\circ', '°').replace(r'\pm', '±').replace(r'\leq', '≤').replace(r'\geq', '≥').replace(r'\neq', '≠').replace(r'\approx', '≈').replace(r'\pi', 'π').replace(r'\sqrt', '√').replace('\\', '')
    s = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1/\2', s)
    return re.sub(r"(?<!\*)\*(\S.+?)\*(?!\*)", r"<i>\1</i>", re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")))

def create_pdf(content: str, images=None, filename="Question_Paper.pdf"):
    buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=0.75*inch, leftMargin=0.75*inch, topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CustomTitle", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#00d4ff"), spaceAfter=12, alignment=TA_CENTER, fontName="Helvetica-Bold")
    body_style = ParagraphStyle("CustomBody", parent=styles["BodyText"], fontSize=11, spaceAfter=8, alignment=TA_LEFT, fontName="Helvetica")
    story, img_idx, table_rows = [], 0,[]

    def render_pending_table():
        nonlocal table_rows
        if not table_rows: return
        ncols = max(len(r) for r in table_rows)
        norm_rows = [[Paragraph(md_inline_to_rl(c), body_style) for c in list(r) + [""] * (ncols - len(r))] for r in table_rows]
        t = Table(norm_rows, colWidths=[doc.width / max(1, ncols)] * ncols)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00d4ff")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "LEFT"), ("BOTTOMPADDING", (0, 0), (-1, 0), 8), ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")), ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
        story.extend([t, Spacer(1, 0.18*inch)]); table_rows = []

    lines =[re.sub(r"\s*\(Source:.*?\)", "", l).strip() for l in str(content or "⚠️ No content").split("\n") if "[PDF_READY]" not in l.upper() and not l.strip().startswith(("Source(s):", "**Source(s):**"))]
    
    for s in lines:
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            cells =[c.strip() for c in s.split("|")[1:-1]]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells if c): table_rows.append(cells)
            continue
        render_pending_table()
        if not s: story.append(Spacer(1, 0.14*inch)); continue
        if s.startswith(("IMAGE_GEN:", "PIE_CHART:")):
            if images and img_idx < len(images) and images[img_idx]:
                try:
                    img_stream = BytesIO(images[img_idx]); rl_reader = ImageReader(img_stream)
                    iw, ih = rl_reader.getSize()
                    story.extend([Spacer(1, 0.12*inch), RLImage(img_stream, width=4.6*inch, height=4.6*inch*(ih/float(iw))), Spacer(1, 0.12*inch)])
                except Exception: pass
            img_idx += 1; continue
        if s.startswith("# "): story.append(Paragraph(md_inline_to_rl(s[2:].strip()), title_style))
        elif s.startswith("## "): story.append(Paragraph(md_inline_to_rl(s[3:].strip()), ParagraphStyle("CustomHeading", parent=styles["Heading2"], fontSize=14, spaceAfter=10, spaceBefore=10, fontName="Helvetica-Bold")))
        elif s.startswith("### "): story.append(Paragraph(f"<b>{md_inline_to_rl(s[4:].strip())}</b>", body_style))
        else: story.append(Paragraph(md_inline_to_rl(s), body_style))
    render_pending_table(); story.extend([Spacer(1, 0.28*inch), Paragraph("<i>Generated by helix.ai - Your CIE Tutor</i>", body_style)])
    doc.build(story); buffer.seek(0)
    return buffer

def safe_response_text(resp) -> str:
    try: return str(resp.text) if getattr(resp, "text", None) else "\n".join([p.text for c in (getattr(resp, "candidates", []) or[]) for p in (getattr(c.content, "parts", []) or[]) if getattr(p, "text", None)])
    except Exception: return ""

def generate_chat_title(client, messages):
    try:
        user_msgs =[m.get("content", "") for m in messages if m.get("role") == "user"]
        if not user_msgs: return "New Chat"
        response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=["Summarize this into a short chat title (max 4 words). Context: " + "\n".join(user_msgs[-3:])], config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=50))
        return safe_response_text(response).strip().replace('"', '').replace("'", "") or "New Chat"
    except Exception: return "New Chat"

# -----------------------------
# 3) SESSION STATE & DIALOGS
# -----------------------------
if "current_thread_id" not in st.session_state: st.session_state.current_thread_id = str(uuid.uuid4())
if "messages" not in st.session_state: st.session_state.messages = get_default_greeting()
if "delete_requested_for" not in st.session_state: st.session_state.delete_requested_for = None

@st.dialog("⚠️ Maximum Chats")
def confirm_new_chat_dialog(oldest_thread_id):
    st.write("Limit of 15 chats reached. Delete oldest to create new?")
    c1, c2 = st.columns(2)
    if c1.button("Cancel", use_container_width=True): st.rerun()
    if c2.button("Yes", type="primary", use_container_width=True):
        try: get_threads_collection().document(oldest_thread_id).delete()
        except Exception: pass
        st.session_state.current_thread_id = str(uuid.uuid4()); st.session_state.messages = get_default_greeting(); st.rerun()

@st.dialog("🗑️ Delete Chat")
def confirm_delete_chat_dialog(thread_id_to_delete):
    st.write("Permanently delete this chat?")
    c1, c2 = st.columns(2)
    if c1.button("Cancel", use_container_width=True): st.session_state.delete_requested_for = None; st.rerun()
    if c2.button("Yes", type="primary", use_container_width=True):
        try: get_threads_collection().document(thread_id_to_delete).delete()
        except Exception: pass
        if st.session_state.current_thread_id == thread_id_to_delete: st.session_state.current_thread_id = str(uuid.uuid4()); st.session_state.messages = get_default_greeting()
        st.session_state.delete_requested_for = None; st.rerun()

@st.dialog("⚙️ Chat Settings")
def chat_settings_dialog(thread_data):
    st.caption(f"📚 **Subjects:** {', '.join(thread_data.get('metadata', {}).get('subjects',[])) or 'None'}")
    st.caption(f"🎓 **Grades:** {', '.join(thread_data.get('metadata', {}).get('grades',[])) or 'None'}")
    new_title = st.text_input("Rename Chat", value=thread_data.get("title", "New Chat"))
    if st.button("💾 Save", use_container_width=True):
        get_threads_collection().document(thread_data["id"]).set({"title": new_title, "user_edited_title": True}, merge=True); st.rerun()
    if st.button("🗑️ Delete", type="primary", use_container_width=True):
        st.session_state.delete_requested_for = thread_data['id']; st.rerun()

# =====================================================================
# 🔴 HELIX ADMIN MODE
# =====================================================================
ADMIN_VERIFICATION_CODE = st.secrets.get("ADMIN_VERIFICATION_CODE")

def render_admin_panel():
    
    if not is_authenticated or auth_object.email not in st.secrets.get("ADMIN_EMAILS",[]):
        st.error("Unauthorized."); st.button("Return Home", on_click=lambda: st.session_state.update(current_page="chat")); return

    if not st.session_state.get("admin_authenticated"):
        st.markdown(f'<div class="admin-login-box"><h2 style="color:#ff4d6d;margin-bottom:6px;">🔐 Admin Access</h2><p style="color:rgba(255,150,160,0.6);font-size:0.85rem;">Welcome {auth_object.email}.</p></div>', unsafe_allow_html=True)
        with st.form("admin_login"):
            if st.form_submit_button("🔓 Access Admin") and st.text_input("Code", type="password") == ADMIN_VERIFICATION_CODE:
                st.session_state.update(admin_authenticated=True, admin_email=auth_object.email); st.rerun()
        return

    st.markdown(f'<div class="admin-header"><div class="admin-title">⚙️ Helix Admin Console</div><div style="color:rgba(255,150,160,0.6);font-size:0.85rem;margin-top:4px;">Logged in as {auth_object.email}</div></div>', unsafe_allow_html=True)

    admin_school_filter = "All Schools"
    with st.sidebar:
        st.markdown("<b style='color:#ff4d6d'>ADMIN NAVIGATION</b>", unsafe_allow_html=True)
        admin_page = st.radio("Navigation",["📊 Dashboard", "🎓 Students", "👩‍🏫 Teachers", "🏫 Classes", "🧪 AI Debug Lab"], label_visibility="collapsed")
        
        st.markdown("---")
        st.markdown("<b style='color:#ff4d6d'>🏫 SCHOOL FILTER</b>", unsafe_allow_html=True)
        all_schools = sorted(list(set([u.to_dict().get("school") for u in db.collection("users").where(filter=firestore.FieldFilter("role", "==", "teacher")).stream() if u.to_dict().get("school")]).union(SCHOOL_CODES.values())))
        admin_school_filter = st.selectbox("School Filter", ["All Schools"] + all_schools, label_visibility="collapsed")
        
        st.markdown("---")
        if st.button("🚪 Exit Admin", use_container_width=True): st.session_state.update(admin_authenticated=False, current_page="chat"); st.rerun()

    if admin_page == "📊 Dashboard":
        st.markdown(f'<div class="section-header">📊 System Overview ({admin_school_filter})</div>', unsafe_allow_html=True)
        u_query = db.collection("users").stream() if admin_school_filter == "All Schools" else db.collection("users").where(filter=firestore.FieldFilter("school", "==", admin_school_filter)).stream()
        users =[u.to_dict() for u in u_query]
        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div class="stat-card"><div class="stat-number">{sum(1 for u in users if u.get("role") == "student")}</div><div class="stat-label">Students</div></div>', unsafe_allow_html=True)
        c2.markdown(f'<div class="stat-card"><div class="stat-number">{sum(1 for u in users if u.get("role") == "teacher")}</div><div class="stat-label">Teachers</div></div>', unsafe_allow_html=True)
        
        classes_count = len(list(db.collection("classes").stream() if admin_school_filter == "All Schools" else db.collection("classes").where(filter=firestore.FieldFilter("school", "==", admin_school_filter)).stream()))
        c3.markdown(f'<div class="stat-card"><div class="stat-number">{classes_count}</div><div class="stat-label">Classes</div></div>', unsafe_allow_html=True)

    elif admin_page == "🎓 Students":
        st.markdown(f'<div class="section-header">🎓 Manage Students ({admin_school_filter})</div>', unsafe_allow_html=True)
        try:
            if admin_school_filter == "All Schools":
                students =[{"id": d.id, **d.to_dict()} for d in db.collection("users").where(filter=firestore.FieldFilter("role", "==", "student")).stream()]
            else:
                school_users = db.collection("users").where(filter=firestore.FieldFilter("school", "==", admin_school_filter)).stream()
                students =[{"id": d.id, **d.to_dict()} for d in school_users if d.to_dict().get("role") == "student"]
            
            if students:
                st.table([{"Name": s.get("display_name", "—"), "Email": s.get("id", "—"), "Grade": s.get("grade", "—"), "School": s.get("school", "—")} for s in students])
            else:
                st.info("No students registered for this filter.")
        except Exception as e: st.error(str(e))
        
        st.markdown('<div class="section-header">🗑️ Delete Student</div>', unsafe_allow_html=True)
        del_id = st.text_input("Enter Student Email to Delete")
        cascade = st.checkbox("Also delete their chat threads and analytics history", value=True)
        if st.button("Permanently Delete Student", type="primary"):
            if del_id:
                try:
                    db.collection("users").document(del_id).delete()
                    if cascade:
                        for t in db.collection("users").document(del_id).collection("threads").stream(): t.reference.delete()
                        for a in db.collection("users").document(del_id).collection("analytics").stream(): a.reference.delete()
                    st.success(f"Deleted student {del_id}")
                except Exception as e: st.error(str(e))

    elif admin_page == "👩‍🏫 Teachers":
        st.markdown(f'<div class="section-header">👩‍🏫 Manage Teachers ({admin_school_filter})</div>', unsafe_allow_html=True)
        try:
            if admin_school_filter == "All Schools":
                teachers =[{"id": d.id, **d.to_dict()} for d in db.collection("users").where(filter=firestore.FieldFilter("role", "==", "teacher")).stream()]
            else:
                school_users = db.collection("users").where(filter=firestore.FieldFilter("school", "==", admin_school_filter)).stream()
                teachers =[{"id": d.id, **d.to_dict()} for d in school_users if d.to_dict().get("role") == "teacher"]

            if teachers:
                st.table([{"Name": t.get("display_name", "—"), "Email": t.get("id", "—"), "School": t.get("school", "—")} for t in teachers])
            else:
                st.info("No teachers registered for this filter.")
        except Exception as e: st.error(str(e))
        
        st.markdown('<div class="section-header">🗑️ Delete Teacher</div>', unsafe_allow_html=True)
        del_t = st.text_input("Enter Teacher Email to delete")
        if st.button("Delete Teacher", type="primary") and del_t:
            db.collection("users").document(del_t).delete()
            st.success("Deleted")

    elif admin_page == "🏫 Classes":
        st.markdown(f'<div class="section-header">🏫 Manage Classes ({admin_school_filter})</div>', unsafe_allow_html=True)
        try:
            if admin_school_filter == "All Schools":
                classes =[{"id": d.id, **d.to_dict()} for d in db.collection("classes").stream()]
            else:
                classes =[{"id": d.id, **d.to_dict()} for d in db.collection("classes").where(filter=firestore.FieldFilter("school", "==", admin_school_filter)).stream()]

            if classes:
                st.table([{"Class ID": c.get("id", "—"), "Grade": c.get("grade", "—"), "School": c.get("school", "—")} for c in classes])
            else:
                st.info("No classes created for this filter.")
        except Exception as e: st.error(str(e))
        
        st.markdown('<div class="section-header">🗑️ Delete Class</div>', unsafe_allow_html=True)
        del_c = st.text_input("Enter Class ID to delete")
        if st.button("Delete Class", type="primary") and del_c:
            db.collection("classes").document(del_c).delete()
            st.success("Deleted")

    elif admin_page == "🧪 AI Debug Lab":
        st.markdown('<div class="section-header">🧪 AI Debug Lab</div>', unsafe_allow_html=True)
        m_choice = st.selectbox("Model",["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3.1-pro-preview"])
        d_prompt = st.text_area("Prompt")
        if st.button("▶️ Run"):
            with st.spinner("Running..."):
                try:
                    if "image" in m_choice.lower():
                        res = process_visual_wrapper(("IMAGE_GEN", d_prompt))
                        if res[0]: st.image(res[0])
                        else: st.error(res[2])
                    else:
                        st.code(safe_response_text(client.models.generate_content(model=m_choice, contents=d_prompt)))
                except Exception as e: st.error(e)

if st.session_state.get("current_page") == "admin": render_admin_panel(); st.stop()

# -----------------------------
# 4) SIDEBAR
# -----------------------------
with st.sidebar:
    if is_authenticated and user_email.lower() in[e.lower() for e in st.secrets.get("ADMIN_EMAILS",[])] and st.button("⚙️ Admin Panel"):
        st.session_state.current_page = "admin"; st.rerun()

    if not is_authenticated:
        st.markdown("Chatting as a Guest!\nLog in with Google to save history!")
        if st.button("Log in with Google", type="primary", use_container_width=True): st.login(provider="google")
    else:
        st.success(f"Welcome back, {user_profile.get('display_name', 'User')}!")
        if st.button("Log out", use_container_width=True): st.logout()
        st.divider()

        if user_role == "student":
            if not user_profile.get("teacher_id"):
                with st.expander("🎓 Are you a Teacher?"):
                    if st.button("Verify Code") and (code_input := st.text_input("Teacher Code", type="password")) in SCHOOL_CODES:
                        db.collection("users").document(user_email).update({"role": "teacher", "school": SCHOOL_CODES[code_input]})
                        st.success("Verified!"); time.sleep(1); st.rerun()
            else:
                c = get_student_class_data(user_email)
                st.info(f"🏫 Class:\n**{c.get('id', 'Unknown') if c else 'Unknown'}**")

    if st.button("➕ New Chat", use_container_width=True):
        if is_authenticated and len(get_all_threads()) >= 15: confirm_new_chat_dialog(get_all_threads()[-1]["id"])
        else: st.session_state.current_thread_id = str(uuid.uuid4()); st.session_state.messages = get_default_greeting(); st.rerun()

    if is_authenticated:
        for t in get_all_threads():
            c1, c2 = st.columns([0.85, 0.15], vertical_alignment="center")
            if c1.button(f"{'🟢' if t['id'] == st.session_state.current_thread_id else '💬'} {t.get('title', 'New Chat')}", key=f"btn_{t['id']}", use_container_width=True):
                st.session_state.current_thread_id = t["id"]; st.session_state.messages = load_chat_history(t["id"]); st.rerun()
            if c2.button("⋮", key=f"set_{t['id']}", use_container_width=True): chat_settings_dialog(t)

if st.session_state.delete_requested_for: confirm_delete_chat_dialog(st.session_state.delete_requested_for)

def get_friendly_name(filename: str) -> str:
    name = (filename or "").replace(".pdf", "").replace(".PDF", "")
    parts = name.split("_")
    if len(parts) < 3 or parts[0] != "CIE": return name or "Textbook"
    return f"Cambridge {'Science' if 'Sci' in parts else 'Math' if 'Math' in parts else 'English'} {'Workbook' if 'WB' in parts else 'Textbook'}{' Answers' if 'ANSWERS' in parts else ''} {parts[1]} {'(Part 1)' if '1' in parts[2:] else '(Part 2)' if '2' in parts[2:] else ''}".strip()

def guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    n = (filename or "").lower()
    return "image/jpeg" if n.endswith((".jpg", ".jpeg")) else "image/png" if n.endswith(".png") else "application/pdf" if n.endswith(".pdf") else fallback

def is_image_mime(m: str) -> bool: return (m or "").lower().startswith("image/")

@st.cache_resource(show_spinner=False)
def upload_textbooks():
    active_files = {"sci":[], "math":[], "eng":[]}
    
    # 1. Dynamically find ALL CIE pdfs in your folder! No more hardcoding names.
    pdf_map = {p.name.lower(): p for p in Path.cwd().rglob("*.pdf") if "cie" in p.name.lower()}
    target_files = list(pdf_map.keys())
    
    try: existing = {f.display_name.lower(): f for f in client.files.list() if f.display_name}
    except Exception: existing = {}
    
    with st.chat_message("assistant"): st.markdown(f"""<div class="thinking-container"><span class="thinking-text">📚 Synchronizing {len(target_files)} Textbooks...</span><div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div></div>""", unsafe_allow_html=True)
    
    def process_single_book(t):
        if t in existing and existing[t].state.name == "ACTIVE": return t, existing[t]
        if t in pdf_map:
            try:
                up = client.files.upload(file=str(pdf_map[t]), config={"mime_type": "application/pdf", "display_name": pdf_map[t].name})
                timeout = time.time() + 90
                while up.state.name == "PROCESSING" and time.time() < timeout:
                    time.sleep(3)
                    up = client.files.get(name=up.name)
                if up.state.name == "ACTIVE": return t, up
            except Exception as e: print(f"Upload Error {t}: {e}")
        return t, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(process_single_book, target_files))

    for t, file_obj in results:
        if file_obj:
            if "sci" in t: active_files["sci"].append(file_obj)
            elif "math" in t: active_files["math"].append(file_obj)
            elif "eng" in t: active_files["eng"].append(file_obj)
    return active_files

if is_authenticated and "textbook_handles" not in st.session_state:
    with st.spinner("Preparing curriculum..."): st.session_state.textbook_handles = upload_textbooks()

def select_relevant_books(query, file_dict, user_grade="Grade 6"):
    qn = normalize_stage_text(query)
    s7 = any(k in qn for k in["stage 7", "grade 6", "year 7"])
    s8 = any(k in qn for k in["stage 8", "grade 7", "year 8"])
    s9 = any(k in qn for k in["stage 9", "grade 8", "year 9"])
    
    im = any(k in qn for k in["math", "algebra", "number", "fraction", "geometry", "calculate", "equation"])
    isc = any(k in qn for k in["sci", "biology", "physics", "chemistry", "experiment", "cell", "gravity"])
    ien = any(k in qn for k in["eng", "poem", "story", "essay", "writing", "grammar"])
    
    if not (s7 or s8 or s9):
        if user_grade == "Grade 6": s7 = True
        elif user_grade == "Grade 7": s8 = True
        elif user_grade == "Grade 8": s9 = True
        else: s8 = True
        
    if not (im or isc or ien): im = isc = ien = True
    sel =[]
    def add(k, act):
        if act: 
            for b in file_dict.get(k,[]):
                n = b.display_name.lower()
                if (s7 and "cie_7" in n) or (s8 and "cie_8" in n) or (s9 and "cie_9" in n): sel.append(b)
    
    add("math", im); add("sci", isc); add("eng", ien)
    return sel[:3]

# ==========================================
# APP ROUTING: TEACHER DASHBOARD
# ==========================================
render_chat_interface = False 

if user_role == "teacher":
    st.markdown("<div class='big-title' style='color:#fc8404;'>👨‍🏫 helix.ai / Teacher</div>", unsafe_allow_html=True)
    # Native Streamlit Text overridden via CSS for exact visual matching & SEO optimization
    st.text("helix.ai Teacher Dashboard: Manage Cambridge (CIE) classes, track student analytics, and generate detailed, multi-step question papers.")
    
    user_school = user_profile.get("school")
    roster =[u for u in db.collection("users").where(filter=firestore.FieldFilter("school", "==", user_school)).stream() if u.to_dict().get("role") == "student"] if user_school else list(db.collection("users").where(filter=firestore.FieldFilter("teacher_id", "==", user_email)).stream())

    teacher_menu = st.radio("Menu",["Class Management", "Student Analytics", "Assign Papers", "AI Chat"], horizontal=True, label_visibility="collapsed")
    st.divider()

    if teacher_menu == "Class Management":
        st.subheader("🏫 Class Management")
        with st.form("create_class_form", clear_on_submit=True):
            cc1, cc2, cc3 = st.columns([0.4, 0.3, 0.3])
            grade_choice = cc1.selectbox("Grade",["Grade 6", "Grade 7", "Grade 8"])
            section_choice = cc2.selectbox("Section",["A", "B", "C", "D"])
            if cc3.form_submit_button("Create", use_container_width=True):
                success, msg = create_global_class(f"{grade_choice.split()[-1]}{section_choice}".upper(), user_email, grade_choice, section_choice, user_school)
                if success: st.success(msg); time.sleep(1); st.rerun()
                else: st.error(msg)
        
        my_classes = list(db.collection("classes").where(filter=firestore.FieldFilter("created_by", "==", user_email)).stream())
        if my_classes:
            with st.form("add_student_form", clear_on_submit=True):
                sc = st.selectbox("Class",[c.id for c in my_classes])
                em = st.text_input("Student Email")
                if st.form_submit_button("Add") and em:
                    db.collection("users").document(em.strip().lower()).set({"role": "student", "teacher_id": user_email, "school": user_school}, merge=True)
                    db.collection("classes").document(sc).update({"students": firestore.ArrayUnion([em.strip().lower()])})
                    st.success("Added!"); time.sleep(1); st.rerun()

    elif teacher_menu == "Assign Papers":
        st.subheader("📝 Assignment Creator")
        c1, c2 = st.columns(2)
        assign_title = c1.text_input("Title", "Chapter Quiz")
        assign_subject = c1.selectbox("Subject",["Math", "Biology", "Chemistry", "Physics", "English"])
        assign_grade = c1.selectbox("Grade",["Grade 6", "Grade 7", "Grade 8"])
        assign_difficulty = c2.selectbox("Difficulty",["Easy", "Medium", "Hard"])
        assign_marks = c2.number_input("Marks", 10, 100, 30, 5)
        assign_extra = st.text_area("Extra Instructions")

        if st.button("🤖 Generate with Helix AI", type="primary", use_container_width=True):
            with st.spinner("Writing paper..."):
                books = select_relevant_books(f"{assign_subject} {assign_grade}", st.session_state.textbook_handles, assign_grade)
                parts =[]
                for b in books: parts.extend([types.Part.from_text(text=f"[Source: {b.display_name}]"), types.Part.from_uri(file_uri=b.uri, mime_type="application/pdf")])
                
                parts.append(types.Part.from_text(text=f"Task: Generate a CIE {assign_subject} paper for {GRADE_TO_STAGE[assign_grade]} ({assign_grade}). Difficulty: {assign_difficulty}. Marks: {assign_marks}. Extra: {assign_extra}. Append [PDF_READY] at end."))
                
                try:
                    resp = client.models.generate_content(model="gemini-2.5-pro", contents=parts, config=types.GenerateContentConfig(system_instruction=PAPER_SYSTEM, temperature=0.1))
                    gen_paper = safe_response_text(resp)
                    
                    draft_imgs, draft_mods = [],[]
                    if v_prompts := re.findall(r"(IMAGE_GEN|PIE_CHART):\s*\[(.*?)\]", gen_paper):
                        with concurrent.futures.ThreadPoolExecutor(5) as exe:
                            for r in exe.map(process_visual_wrapper, v_prompts):
                                draft_imgs.append(r[0]); draft_mods.append(r[1])
                                if not r[0] and len(r)>2: st.error(f"Image Error: {r[2]}")

                    st.session_state.update(draft_paper=gen_paper, draft_images=draft_imgs, draft_models=draft_mods, draft_title=assign_title); st.rerun()
                except Exception as e: st.error(e)

        if st.session_state.get("draft_paper"):
            with st.expander("Preview", expanded=True):
                st.markdown(st.session_state.draft_paper.replace("[PDF_READY]", ""))
                if st.session_state.draft_images:
                    for i, m in zip(st.session_state.draft_images, st.session_state.draft_models):
                        if i: st.image(i, caption=m)
                try: st.download_button("Download PDF", data=create_pdf(st.session_state.draft_paper, st.session_state.draft_images), file_name=f"{st.session_state.draft_title}.pdf", mime="application/pdf")
                except Exception as e: st.error(f"PDF Gen Error: {e}")

    elif teacher_menu == "AI Chat": render_chat_interface = True 

else:
    render_chat_interface = True
    st.markdown("<div class='big-title'>📚 helix.ai</div>", unsafe_allow_html=True)
    # Native Streamlit Text overridden via CSS for exact visual matching & SEO optimization
    st.text("helix.ai: Your AI-powered Cambridge (CIE) Tutor for Grade 6-8. Master Math, Science, and English with deep, interactive learning.")

# ==========================================
# UNIVERSAL CHAT VIEW 
# ==========================================
if render_chat_interface:
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            # Aggressive Regex Sweeper: Removes tags and stray JSON blocks
            disp = re.sub(r"===ANALYTICS_START===.*?===ANALYTICS_END===", "", msg.get("content") or "", flags=re.IGNORECASE|re.DOTALL)
            disp = re.sub(r"```json\s*\{[^{]*?\"weak_point\".*?\}\s*```", "", disp, flags=re.IGNORECASE|re.DOTALL)
            disp = re.sub(r"\{[^{]*?\"weak_point\".*?\}", "", disp, flags=re.IGNORECASE|re.DOTALL)
            disp = re.sub(r"\[PDF_READY\]", "", disp, flags=re.IGNORECASE).strip()
            
            st.markdown(disp)
            
            for img, mod in zip(msg.get("images") or[], msg.get("image_models",["Unknown"]*10)):
                if img: st.image(img, use_container_width=True, caption=f"✨ Generated by helix.ai ({mod})")
            for b64, mod in zip(msg.get("db_images") or [], msg.get("image_models", ["Unknown"]*10)):
                if b64:
                    try: st.image(base64.b64decode(b64), use_container_width=True, caption=f"✨ Generated by helix.ai ({mod})")
                    except: pass
            if msg.get("user_attachment_bytes"):
                mime, name = msg.get("user_attachment_mime", ""), msg.get("user_attachment_name", "File")
                if "image" in mime: st.image(msg["user_attachment_bytes"], use_container_width=True)
                else: st.caption(f"📎 Attached: {name}")

            if msg["role"] == "assistant" and msg.get("is_downloadable"):
                try: st.download_button("📄 Download PDF", data=create_pdf(msg.get("content") or "", msg.get("images") or[base64.b64decode(b) for b in msg.get("db_images",[]) if b]), file_name=f"Paper_{idx}.pdf", mime="application/pdf", key=f"dl_{idx}")
                except Exception as e: st.error(f"PDF Error: {e}")

    if chat_input := st.chat_input("Ask Helix...", accept_file=True, file_type=["jpg","png","pdf","txt"]):
        if "textbook_handles" not in st.session_state: st.session_state.textbook_handles = upload_textbooks()
        
        f_bytes = chat_input.files[0].getvalue() if chat_input.files else None
        f_mime = chat_input.files[0].type if chat_input.files else None
        f_name = chat_input.files[0].name if chat_input.files else None
        
        st.session_state.messages.append({"role": "user", "content": chat_input.text or "", "user_attachment_bytes": f_bytes, "user_attachment_mime": f_mime, "user_attachment_name": f_name})
        save_chat_history(); st.rerun()

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        msg_data = st.session_state.messages[-1]
        with st.chat_message("assistant"):
            think = st.empty(); think.markdown("""<div class="thinking-container"><span class="thinking-text">Thinking</span><div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div></div>""", unsafe_allow_html=True)
            
            try:
                valid_history =[]
                exp_role = "model"
                for m in reversed([m for m in st.session_state.messages[:-1] if not m.get("is_greeting")]):
                    r = "user" if m.get("role") == "user" else "model"
                    txt = m.get("content") or ""
                    if txt.strip() and r == exp_role:
                        valid_history.insert(0, types.Content(role=r, parts=[types.Part.from_text(text=txt)]))
                        exp_role = "user" if exp_role == "model" else "model"
                if valid_history and valid_history[0].role == "model": valid_history.pop(0)

                curr_parts =[]
                # Explicitly pass the student's grade to make book matching bulletproof
                student_grade = user_profile.get("grade", "Grade 6")
                books = select_relevant_books(" ".join([m.get("content","") for m in st.session_state.messages[-3:]]), st.session_state.textbook_handles, student_grade)
                
                if books:
                    st.caption(f"📚 **Reading Textbooks:** {', '.join([get_friendly_name(b.display_name) for b in books])}")
                    for b in books: 
                        curr_parts.append(types.Part.from_text(text=f"--- START OF SOURCE TEXTBOOK: {b.display_name} ---"))
                        curr_parts.append(types.Part.from_uri(file_uri=b.uri, mime_type="application/pdf"))
                        curr_parts.append(types.Part.from_text(text=f"--- END OF SOURCE TEXTBOOK ---"))
                
                if f_bytes := msg_data.get("user_attachment_bytes"):
                    mime = msg_data.get("user_attachment_mime") or guess_mime(msg_data.get("user_attachment_name"))
                    if is_image_mime(mime): curr_parts.append(types.Part.from_bytes(data=f_bytes, mime_type=mime))
                    elif "pdf" in mime:
                        tmp = f"temp_{time.time()}.pdf"
                        with open(tmp, "wb") as f: f.write(f_bytes)
                        up = client.files.upload_file(tmp)
                        while up.state.name == "PROCESSING": time.sleep(1); up = client.files.get(name=up.name)
                        curr_parts.append(types.Part.from_uri(file_uri=up.uri, mime_type="application/pdf"))
                        os.remove(tmp)

                curr_parts.append(types.Part.from_text(text=f"Please analyze the attached Cambridge textbooks and files. You MUST use the book's facts and terminology.\n\nUser Query: {msg_data.get('content')}"))
                
                resp = client.models.generate_content(
                    model="gemini-3.1-flash-lite-preview",
                    contents=valid_history +[types.Content(role="user", parts=curr_parts)],
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION, temperature=0.3, tools=[{"google_search": {}}])
                )
                bot_txt = safe_response_text(resp) or "⚠️ *Failed to generate text.*"
                
                # Strict Boundary Analytics Extraction
                am = re.search(r"===ANALYTICS_START===(.*?)===ANALYTICS_END===", bot_txt, flags=re.IGNORECASE|re.DOTALL)
                if not am: 
                    # Fallback if model just prints JSON
                    am = re.search(r"(\{[\s\S]*?\"weak_point\"[\s\S]*?\})", bot_txt, flags=re.IGNORECASE)
                
                if am:
                    try:
                        ad = json.loads(am.group(1))
                        bot_txt = bot_txt.replace(am.group(0), "").strip()
                        if is_authenticated and db: db.collection("users").document(user_email).collection("analytics").add({"timestamp": time.time(), **ad})
                    except Exception: pass

                think.empty()
                
                imgs, mods = [],[]
                if v_prompts := re.findall(r"(IMAGE_GEN|PIE_CHART):\s*\[(.*?)\]", bot_txt):
                    with concurrent.futures.ThreadPoolExecutor(5) as exe:
                        for r in exe.map(process_visual_wrapper, v_prompts):
                            if r and r[0]: imgs.append(r[0]); mods.append(r[1])
                            else: imgs.append(None); mods.append("Failed")
                
                dl = bool(re.search(r"\[PDF_READY\]", bot_txt, re.IGNORECASE) or (re.search(r"##\s*Mark Scheme", bot_txt, re.IGNORECASE) and re.search(r"\[\d+\]", bot_txt)))
                st.session_state.messages.append({"role": "assistant", "content": bot_txt, "is_downloadable": dl, "images": imgs, "image_models": mods})
                
                if is_authenticated and sum(1 for m in st.session_state.messages if m["role"] == "user") == 1:
                    t = generate_chat_title(client, st.session_state.messages)
                    if t: get_threads_collection().document(st.session_state.current_thread_id).set({"title": t}, merge=True)
                
                save_chat_history(); st.rerun()
                
            except Exception as e: think.empty(); st.error(f"Error: {e}")
