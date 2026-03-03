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
# 1.5) STAGE NORMALIZATION
# -----------------------------
NUM_WORDS = {
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9",
}

def normalize_stage_text(s: str) -> str:
    s = (s or "").lower()
    for w, d in NUM_WORDS.items():
        s = re.sub(rf"\b{w}\b", d, s)
    return s

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
            "role": "student",
            "teacher_id": None,
            "display_name": google_name,
            "grade": None
        }
        doc_ref.set(default_profile)
        return default_profile

def create_global_class(class_name, teacher_email):
    if not db: return False, "Database error."
    clean_name = class_name.strip().upper()
    if not clean_name:
        return False, "Class name cannot be empty."
    class_ref = db.collection("classes").document(clean_name)

    @firestore.transactional
    def check_and_create(transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if snapshot.exists:
            return False, f"Class '{clean_name}' already exists in the system!"
        transaction.set(ref, {
            "created_by": teacher_email,
            "created_at": time.time(),
            "students": [],
            "subjects": []
        })
        return True, f"Class '{clean_name}' successfully created!"

    transaction = db.transaction()
    return check_and_create(transaction, class_ref)

user_role = "guest"
if is_authenticated:
    user_email = auth_object.email
    user_profile = get_user_profile(user_email)
    user_role = user_profile.get("role", "student")

# -----------------------------
# THREAD HELPERS
# -----------------------------
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

def compress_image_for_db(image_bytes: bytes) -> str:
    try:
        if not image_bytes: return None
        img = Image.open(BytesIO(image_bytes))
        if img.mode != 'RGB': img = img.convert('RGB')
        img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"Image compression error: {e}")
        return None

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
            if re.search(r"\bstage\W*7\b", qn) or re.search(r"\bgrade\W*6\b", qn): detected_grades.add("Stage 7")
            if re.search(r"\bstage\W*8\b", qn) or re.search(r"\bgrade\W*7\b", qn): detected_grades.add("Stage 8")
            if re.search(r"\bstage\W*9\b", qn) or re.search(r"\bgrade\W*8\b", qn): detected_grades.add("Stage 9")

        db_images = []
        if msg.get("images"):
            for img_bytes in msg["images"]:
                if img_bytes:
                    compressed_b64 = compress_image_for_db(img_bytes)
                    if compressed_b64: db_images.append(compressed_b64)
        elif msg.get("db_images"):
            db_images = msg["db_images"]

        safe_messages.append({
            "role": str(role),
            "content": content_str,
            "is_greeting": bool(msg.get("is_greeting", False)),
            "is_downloadable": bool(msg.get("is_downloadable", False)),
            "db_images": db_images
        })

    data = {
        "messages": safe_messages,
        "updated_at": time.time(),
        "metadata": {"subjects": list(detected_subjects), "grades": list(detected_grades)},
    }
    try:
        coll_ref.document(current_id).set(data, merge=True)
    except Exception as e:
        st.toast(f"⚠️ Database Error: Could not save chat - {e}")

# -----------------------------
# 2.5) AUTO-TITLE
# -----------------------------
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
        context_text = "\n".join(user_msgs[-3:])
        prompt = (
            "Summarize this conversation context into a very short, punchy chat title (maximum 4 words). "
            "Do not use quotes or punctuation. Context: " + context_text
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=15),
        )
        title = safe_response_text(response).strip().replace('"', '').replace("'", "")
        return title if title else "New Chat"
    except Exception as e:
        print(f"Title Gen Error: {e}")
        return "New Chat"

# -----------------------------
# 3) SESSION STATE
# -----------------------------
if "current_thread_id" not in st.session_state:
    st.session_state.current_thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = get_default_greeting()
if "delete_requested_for" not in st.session_state:
    st.session_state.delete_requested_for = None

# -----------------------------
# 3.5) DIALOGS
# -----------------------------
@st.dialog("⚠️ Maximum Chats Reached")
def confirm_new_chat_dialog(oldest_thread_id):
    st.write("You have hit the maximum limit of **15 saved chats**.")
    st.write("If you create a new chat, your oldest chat will be permanently deleted.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True): st.rerun()
    with col2:
        if st.button("Yes, Create New", type="primary", use_container_width=True):
            coll_ref = get_threads_collection()
            if coll_ref:
                try: coll_ref.document(oldest_thread_id).delete()
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
            coll_ref = get_threads_collection()
            if coll_ref:
                try: coll_ref.document(thread_id_to_delete).delete()
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
        coll_ref = get_threads_collection()
        if coll_ref:
            coll_ref.document(thread_data["id"]).set({"title": new_title, "user_edited_title": True}, merge=True)
        st.rerun()
    st.divider()
    if st.button("🗑️ Delete Chat", key=f"del_btn_set_{thread_data['id']}", type="primary", use_container_width=True):
        st.session_state.delete_requested_for = thread_data["id"]
        st.rerun()

# -----------------------------
# 4) SIDEBAR
# -----------------------------
with st.sidebar:
    st.title("Account Settings")
    if not is_authenticated:
        st.markdown("👋 **You are chatting as a Guest!**\n\n*Log in with Google to save history!*")
        if st.button("Log in with Google", type="primary", use_container_width=True):
            st.login(provider="google")
    else:
        user_name = auth_object.get("name", "User")
        st.success(f"Welcome back, **{user_name}**! ({user_role.capitalize()})")
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
                st.info(f"🏫 Connected to classroom:\n**{assigned_teacher}**")

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

# ==========================================
# APP ROUTING: TEACHER DASHBOARD
# ==========================================
if user_role == "teacher":
    st.markdown("<div class='big-title' style='color:#fc8404;'>👨‍🏫 helix.ai / Teacher</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>Classroom Management & AI Assistant</div>", unsafe_allow_html=True)

    AVAILABLE_SUBJECTS = ["Math", "Biology", "Chemistry", "Physics", "English"]

    # Query roster once — used across multiple tabs
    student_docs_raw = db.collection("users").where(
        filter=firestore.FieldFilter("teacher_id", "==", user_email)
    ).stream()
    roster = list(student_docs_raw)

    # 4 TABS — visible immediately, no expander
    tab1, tab2, tab3, tab4 = st.tabs([
        "⚙️ Class Management",
        "📊 Student Analytics",
        "📝 Assign Papers",
        "💬 AI Chat"
    ])

    # ── TAB 1: CLASS MANAGEMENT ──────────────────────────────────────────
    with tab1:
        st.subheader("🏫 Class Management")
        st.caption("Create unique classes (e.g., 'Class 6A'). Class names are unique across the entire school.")

        with st.form("create_class_form", clear_on_submit=True):
            col_cname, col_cbtn = st.columns([0.8, 0.2])
            with col_cname:
                new_class_name = st.text_input("New Class Name", placeholder="e.g. Class 7B")
            with col_cbtn:
                st.write("")
                submit_class = st.form_submit_button("➕ Create", use_container_width=True)
            if submit_class and new_class_name:
                success, message = create_global_class(new_class_name, user_email)
                if success:
                    st.success(message)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(message)

        st.divider()
        st.subheader("Add Students to a Class")
        my_classes_tab1 = list(db.collection("classes").where(
            filter=firestore.FieldFilter("created_by", "==", user_email)
        ).stream())

        if my_classes_tab1:
            class_names_tab1 = [c.id for c in my_classes_tab1]
            selected_class_for_add = st.selectbox("Select Class to Add Student:", class_names_tab1, key="add_student_class_sel")
            with st.form("add_student_form", clear_on_submit=True):
                col_email, col_btn = st.columns([0.8, 0.2])
                with col_email:
                    new_student_email = st.text_input("Student Email Address")
                with col_btn:
                    st.write("")
                    submit_student = st.form_submit_button("➕ Add", use_container_width=True)
                if submit_student and new_student_email:
                    clean_email = new_student_email.strip().lower()
                    db.collection("users").document(clean_email).set({
                        "role": "student",
                        "teacher_id": user_email
                    }, merge=True)
                    db.collection("classes").document(selected_class_for_add).update({
                        "students": firestore.ArrayUnion([clean_email])
                    })
                    st.success(f"Added {clean_email} to {selected_class_for_add}!")
                    time.sleep(1)
                    st.rerun()

        st.divider()
        st.subheader("Your Active Classes")
        my_classes_list = list(db.collection("classes").where(
            filter=firestore.FieldFilter("created_by", "==", user_email)
        ).stream())

        if not my_classes_list:
            st.info("You haven't created any classes yet.")
        else:
            for c in my_classes_list:
                c_data = c.to_dict()
                c_name = c.id
                current_subjects = c_data.get("subjects", [])
                class_students = c_data.get("students", [])

                with st.expander(f"📁 {c_name}  ·  {len(class_students)} Students  ·  📚 {', '.join(current_subjects) if current_subjects else 'No subjects set'}"):
                    st.caption(f"Created: {time.strftime('%Y-%m-%d', time.localtime(c_data.get('created_at', 0)))}")

                    st.markdown("**Subjects You Teach in This Class:**")
                    st.caption("Only analytics from these subjects will appear in Student Insights.")
                    new_subject_selection = []
                    sub_cols = st.columns(len(AVAILABLE_SUBJECTS))
                    for i, subject in enumerate(AVAILABLE_SUBJECTS):
                        with sub_cols[i]:
                            checked = st.checkbox(subject, value=(subject in current_subjects), key=f"subj_{c_name}_{subject}")
                            if checked: new_subject_selection.append(subject)

                    col_save, col_del = st.columns([0.7, 0.3])
                    with col_save:
                        if st.button("💾 Save Subjects", key=f"save_subj_{c_name}", use_container_width=True):
                            db.collection("classes").document(c_name).update({"subjects": new_subject_selection})
                            st.success("Subjects saved!")
                            time.sleep(0.8)
                            st.rerun()
                    with col_del:
                        if st.button("🗑️ Delete Class", key=f"del_class_{c_name}", type="primary", use_container_width=True):
                            db.collection("classes").document(c_name).delete()
                            st.rerun()

                    st.markdown("**Students in this class:**")
                    if not class_students:
                        st.caption("No students added yet.")
                    else:
                        for s_email in class_students:
                            s_doc = db.collection("users").document(s_email).get()
                            s_name = s_doc.to_dict().get("display_name", s_email.split("@")[0]) if s_doc.exists else s_email.split("@")[0]
                            rc1, rc2 = st.columns([0.85, 0.15])
                            with rc1:
                                st.write(f"🎓 **{s_name}** ({s_email})")
                            with rc2:
                                if st.button("Remove", key=f"rem_{c_name}_{s_email}", use_container_width=True):
                                    db.collection("classes").document(c_name).update({
                                        "students": firestore.ArrayRemove([s_email])
                                    })
                                    db.collection("users").document(s_email).update({"teacher_id": None})
                                    st.rerun()

    # ── TAB 2: STUDENT ANALYTICS ─────────────────────────────────────────
    with tab2:
        st.subheader("📊 Student Insights & Learning Gaps")
        st.caption("AI automatically tracks your students' questions and evaluates their conceptual weaknesses.")

        if not roster:
            st.info("Add students in the Class Management tab to view their analytics.")
        else:
            student_lookup = {}
            for s in roster:
                s_data = s.to_dict()
                s_name = s_data.get("display_name") or s.id.split("@")[0]
                s_grade = s_data.get("grade") or "Grade Unknown"
                student_lookup[s.id] = {"name": s_name, "grade": s_grade}

            search_query = st.text_input("🔍 Search student by name...", placeholder="Type a name to filter")

            all_grades = sorted(set(v["grade"] for v in student_lookup.values()))
            grade_filter = st.selectbox("Filter by Grade:", ["All Grades"] + all_grades)

            # NEW: Time range filter
            time_filter = st.radio(
                "Show interactions from:",
                ["Last 12 Hours", "Last 24 Hours", "Last 3 Days", "Last 7 Days"],
                horizontal=True
            )
            time_map = {
                "Last 12 Hours": 12 * 3600,
                "Last 24 Hours": 24 * 3600,
                "Last 3 Days": 3 * 86400,
                "Last 7 Days": 7 * 86400,
            }
            cutoff_timestamp = time.time() - time_map[time_filter]

            filtered_students = {
                email: info for email, info in student_lookup.items()
                if (search_query.lower() in info["name"].lower() or not search_query)
                and (grade_filter == "All Grades" or info["grade"] == grade_filter)
            }

            if not filtered_students:
                st.warning("No students match your search or filter.")
            else:
                student_display_list = [
                    f"{info['name']} ({info['grade']})" for email, info in filtered_students.items()
                ]
                email_list = list(filtered_students.keys())

                selected_index = st.selectbox(
                    "Select Student:",
                    options=range(len(student_display_list)),
                    format_func=lambda i: student_display_list[i]
                )
                selected_student = email_list[selected_index]
                selected_name = filtered_students[selected_student]["name"]

                if selected_student:
                    st.markdown(f"### 📋 Report for **{selected_name}**")
                    st.caption(f"Showing data from: **{time_filter}**")

                    teacher_subjects = []
                    my_classes_for_filter = db.collection("classes").where(
                        filter=firestore.FieldFilter("created_by", "==", user_email)
                    ).stream()
                    for c in my_classes_for_filter:
                        if selected_student in c.to_dict().get("students", []):
                            teacher_subjects = c.to_dict().get("subjects", [])
                            break

                    analytics_docs = db.collection("users").document(selected_student).collection("analytics").order_by(
                        "timestamp", direction=firestore.Query.DESCENDING
                    ).limit(50).stream()

                    recent_weaknesses = set()
                    recent_questions = []
                    poor_count = 0
                    good_count = 0
                    average_count = 0

                    for doc in analytics_docs:
                        data = doc.to_dict()

                        # Apply time filter
                        if data.get("timestamp", 0) < cutoff_timestamp:
                            continue

                        doc_topic = data.get("topic", "")
                        topic_lower = doc_topic.lower()

                        if teacher_subjects:
                            topic_matches = (
                                ("Math" in teacher_subjects and any(k in topic_lower for k in ["math", "algebra", "geometry", "fraction", "equation"])) or
                                ("Biology" in teacher_subjects and any(k in topic_lower for k in ["biology", "cell", "organism", "plant", "animal", "genetics"])) or
                                ("Chemistry" in teacher_subjects and any(k in topic_lower for k in ["chemistry", "element", "compound", "reaction", "acid", "periodic"])) or
                                ("Physics" in teacher_subjects and any(k in topic_lower for k in ["physics", "force", "gravity", "motion", "energy", "wave", "light"])) or
                                ("English" in teacher_subjects and any(k in topic_lower for k in ["english", "grammar", "poem", "essay", "writing", "story"]))
                            )
                            if not topic_matches:
                                continue

                        level = data.get("understanding_level", "Unknown")
                        if level == "Poor": poor_count += 1
                        elif level == "Average": average_count += 1
                        elif level == "Good": good_count += 1

                        wp = data.get("weak_point")
                        if wp and wp != "None":
                            recent_weaknesses.add(f"{doc_topic}: {wp}")

                        qa = data.get("question_asked")
                        if qa and qa != "None":
                            recent_questions.append(qa)

                    total_interactions = poor_count + average_count + good_count

                    if total_interactions == 0 and not recent_questions:
                        st.info(f"{selected_name} has no interactions in the selected time range.")
                    else:
                        if total_interactions > 0:
                            weighted_score = (good_count * 1.0 + average_count * 0.5 + poor_count * 0.0)
                            health = int((weighted_score / total_interactions) * 100)
                        else:
                            health = 0

                        if health >= 80: score_label = f"{health}% 🟢"
                        elif health >= 50: score_label = f"{health}% 🟡"
                        else: score_label = f"{health}% 🔴"

                        col1, col2, col3 = st.columns(3)
                        with col1: st.metric("Questions Asked", len(recent_questions))
                        with col2: st.metric("Concept Mastery", score_label)
                        with col3: st.metric("Breakdown", f"✅{good_count} 🟡{average_count} ❌{poor_count}")

                        st.divider()
                        col4, col5 = st.columns(2)
                        with col4:
                            st.markdown("🚨 **Identified Weak Points**")
                            if recent_weaknesses:
                                for w in list(recent_weaknesses)[:5]: st.error(w)
                            else:
                                st.success("No major weak points identified!")
                        with col5:
                            st.markdown("💬 **Recently Asked Questions**")
                            if recent_questions:
                                for q in recent_questions[:5]: st.info(q)
                            else:
                                st.write("No direct questions asked recently.")

    # ── TAB 3: ASSIGN PAPERS ─────────────────────────────────────────────
    with tab3:
        st.subheader("📝 Assignment Creator")
        st.caption("Generate a question paper with Helix AI, preview it, and push it to a class or individual student.")

        st.markdown("#### Step 1: Configure Paper")
        col_a, col_b = st.columns(2)
        with col_a:
            assign_title = st.text_input("Assignment Title", placeholder="e.g. Chapter 4 Science Quiz")
            assign_subject = st.selectbox("Subject", ["Math", "Biology", "Chemistry", "Physics", "English"])
            assign_stage = st.selectbox("Stage", ["Stage 7", "Stage 8", "Stage 9"])
        with col_b:
            assign_difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard", "Mixed"])
            assign_marks = st.number_input("Total Marks", min_value=10, max_value=100, value=30, step=5)
            assign_due = st.date_input("Due Date")

        assign_extra = st.text_area(
            "Additional Instructions (optional)",
            placeholder="e.g. Focus on Chapter 4: Forces and Motion. Include 2 diagram questions.",
            height=80
        )

        st.markdown("#### Step 2: Generate Paper")

        # We need the Gemini client here — initialize early placeholder
        _api_key = os.environ.get("GOOGLE_API_KEY") or st.secrets.get("GOOGLE_API_KEY", "")
        _client_ready = False
        try:
            _gen_client = genai.Client(api_key=_api_key)
            _client_ready = True
        except Exception:
            pass

        if st.button("🤖 Generate with Helix AI", use_container_width=True, type="primary"):
            if not _client_ready:
                st.error("Gemini API key not configured.")
            else:
                with st.spinner("Helix is writing your question paper..."):
                    try:
                        gen_prompt = (
                            f"Generate a formal CIE {assign_subject} question paper for {assign_stage} students. "
                            f"Difficulty: {assign_difficulty}. Total marks: {assign_marks}. "
                            f"Include a proper header, numbered questions with marks in brackets, and a mark scheme at the end. "
                            f"Additional instructions: {assign_extra if assign_extra else 'None'}. "
                            f"Follow all formatting rules strictly. Append [PDF_READY] at the end."
                        )
                        gen_response = _gen_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=[gen_prompt],
                            config=types.GenerateContentConfig(temperature=0.3),
                        )
                        generated_paper = safe_response_text(gen_response).strip()
                        generated_paper = re.sub(r"\[ANALYTICS:.*?\]", "", generated_paper, flags=re.DOTALL).strip()
                        st.session_state["draft_paper"] = generated_paper
                        st.session_state["draft_title"] = assign_title or f"{assign_subject} {assign_stage} Paper"
                        st.session_state["draft_due"] = str(assign_due)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

        if st.session_state.get("draft_paper"):
            st.markdown("#### Step 3: Preview & Push to Students")
            with st.expander("👁️ Preview Paper", expanded=True):
                preview_text = st.session_state["draft_paper"].replace("[PDF_READY]", "").strip()
                st.markdown(preview_text)

            try:
                # Need create_pdf defined below — forward reference handled by define order
                from io import BytesIO as _BytesIO
                pdf_buf = create_pdf(st.session_state["draft_paper"])
                st.download_button(
                    label="📥 Download Paper as PDF",
                    data=pdf_buf,
                    file_name=f"{st.session_state['draft_title']}.pdf",
                    mime="application/pdf",
                    key="teacher_pdf_download"
                )
            except Exception: pass

            st.divider()
            st.markdown("#### Step 4: Push Assignment")
            push_mode = st.radio("Push to:", ["Entire Class", "Individual Student"], horizontal=True)

            if push_mode == "Entire Class":
                my_classes_push_raw = db.collection("classes").where(
                    filter=firestore.FieldFilter("created_by", "==", user_email)
                ).stream()
                class_options = {c.id: c.to_dict().get("students", []) for c in my_classes_push_raw}

                if not class_options:
                    st.warning("You haven't created any classes yet.")
                else:
                    target_class = st.selectbox("Select Class:", list(class_options.keys()))
                    student_count = len(class_options.get(target_class, []))
                    st.caption(f"This will push the assignment to **{student_count} students**.")
                    if st.button(f"🚀 Push to {target_class}", use_container_width=True, type="primary"):
                        success_count = 0
                        for s_email in class_options[target_class]:
                            try:
                                db.collection("users").document(s_email).collection("assignments").add({
                                    "title": st.session_state["draft_title"],
                                    "content": st.session_state["draft_paper"],
                                    "assigned_by": user_email,
                                    "assigned_at": time.time(),
                                    "due_date": st.session_state["draft_due"],
                                    "status": "pending",
                                    "class": target_class
                                })
                                success_count += 1
                            except Exception: pass
                        st.success(f"✅ Pushed to {success_count}/{len(class_options[target_class])} students in {target_class}!")
                        del st.session_state["draft_paper"]
                        time.sleep(1)
                        st.rerun()
            else:
                if not roster:
                    st.warning("No students in your roster yet.")
                else:
                    individual_lookup = {}
                    for s in roster:
                        s_data = s.to_dict()
                        s_name = s_data.get("display_name") or s.id.split("@")[0]
                        individual_lookup[s.id] = s_name
                    target_email = st.selectbox(
                        "Select Student:",
                        options=list(individual_lookup.keys()),
                        format_func=lambda e: individual_lookup[e]
                    )
                    if st.button(f"🚀 Push to {individual_lookup[target_email]}", use_container_width=True, type="primary"):
                        try:
                            db.collection("users").document(target_email).collection("assignments").add({
                                "title": st.session_state["draft_title"],
                                "content": st.session_state["draft_paper"],
                                "assigned_by": user_email,
                                "assigned_at": time.time(),
                                "due_date": st.session_state["draft_due"],
                                "status": "pending",
                                "class": "Individual"
                            })
                            st.success(f"✅ Pushed to {individual_lookup[target_email]}!")
                            del st.session_state["draft_paper"]
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")

            if st.button("🗑️ Discard Draft", use_container_width=True):
                del st.session_state["draft_paper"]
                st.rerun()

    # ── TAB 4: AI CHAT (falls through below) ─────────────────────────────
    with tab4:
        st.markdown("Use the AI chat below ⬇️ to generate lesson plans, test ideas, or ask curriculum questions.")

    st.divider()

else:
    st.markdown("<div class='big-title'>📚 helix.ai</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>Your CIE Tutor for Grade 6-8!</div>", unsafe_allow_html=True)

    # Grade selector for students
    if is_authenticated and user_role == "student":
        current_grade = user_profile.get("grade", None)
        GRADE_OPTIONS = ["Grade 6", "Grade 7", "Grade 8", "Grade 9"]
        with st.expander("🎓 Set Your Grade", expanded=(current_grade is None)):
            selected_grade = st.selectbox(
                "Which grade are you in?",
                options=["Select..."] + GRADE_OPTIONS,
                index=0 if not current_grade else (GRADE_OPTIONS.index(current_grade) + 1 if current_grade in GRADE_OPTIONS else 0)
            )
            if st.button("Save Grade"):
                if selected_grade != "Select...":
                    db.collection("users").document(user_email).update({"grade": selected_grade})
                    st.success(f"Grade set to {selected_grade}!")
                    time.sleep(0.8)
                    st.rerun()

# ==========================================
# UNIVERSAL CHAT VIEW
# ==========================================

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
# 6) HELPERS
# -----------------------------
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

# -----------------------------
# 7) VISUAL GENERATORS
# -----------------------------
def generate_single_image(desc: str):
    clean_desc = re.sub(r"\s+", " ", (desc or "")).strip()
    models_to_try = ["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image"]
    for model_name in models_to_try:
        try:
            img_resp = client.models.generate_content(
                model=model_name,
                contents=[clean_desc],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="16:9", image_size="2K")
                ),
            )
            for part in (img_resp.parts or []):
                if getattr(part, "inline_data", None):
                    return part.inline_data.data
        except Exception as e:
            print(f"{model_name} failed: {e}")
            continue
    return None

def generate_pie_chart(data_str: str):
    try:
        labels, sizes = [], []
        for item in str(data_str).split(","):
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
    except Exception as e:
        print(f"Pie chart error: {e}")
    return None

def process_visual(prompt_data):
    trigger_type, data = prompt_data
    if trigger_type == "IMAGE_GEN": return generate_single_image(data)
    if trigger_type == "PIE_CHART": return generate_pie_chart(data)
    return None

# -----------------------------
# 8) PDF EXPORT
# -----------------------------
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
        line = raw.rstrip("\n")
        s = line.strip()
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
        else: story.append(Paragraph(md_inline_to_rl(line), body_style))

    render_pending_table()
    story.append(Spacer(1, 0.28*inch))
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
- For pie charts:
  PIE_CHART: [Label1:Value1, Label2:Value2]

### RULE 6: MARK SCHEME
- Put "## Mark Scheme" at the very bottom. No citations inside mark scheme.

### RULE 7: STUDENT ANALYTICS (HIDDEN)
If the user asks a question about a concept or attempts to answer a question, evaluate their understanding.
At the VERY END of your response, output a hidden JSON block exactly like this:
[ANALYTICS: {"topic": "Topic Name", "understanding_level": "Good/Average/Poor", "weak_point": "Specific gap, or None", "question_asked": "The user's question, or None"}]
Never mention this analytics block in your natural language response.
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
            <span class="thinking-text">📚 Scanning Books...</span>
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
                if "sci" in t: active_files["sci"].append(server_file)
                elif "math" in t: active_files["math"].append(server_file)
                elif "eng" in t: active_files["eng"].append(server_file)
                continue
        found_path = pdf_map.get(t)
        if not found_path: continue
        try:
            uploaded = client.files.upload(
                file=str(found_path),
                config={"mime_type": "application/pdf", "display_name": found_path.name}
            )
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

# -----------------------------
# 11) SMART RAG ROUTING
# -----------------------------
def select_relevant_books(query, file_dict):
    qn = normalize_stage_text(query)
    selected = []
    is_math = any(k in qn for k in ["math", "algebra", "geometry", "calculate", "equation", "number", "fraction"])
    is_sci = any(k in qn for k in ["science", "cell", "biology", "physics", "chemistry", "experiment", "gravity"])
    is_eng = any(k in qn for k in ["english", "poem", "story", "essay", "writing", "grammar", "noun", "verb"])
    stage_7 = bool(re.search(r"\bstage\W*7\b", qn) or re.search(r"\bgrade\W*6\b", qn))
    stage_8 = bool(re.search(r"\bstage\W*8\b", qn) or re.search(r"\bgrade\W*7\b", qn))
    stage_9 = bool(re.search(r"\bstage\W*9\b", qn) or re.search(r"\bgrade\W*8\b", qn))
    has_subject = is_math or is_sci or is_eng
    has_stage = stage_7 or stage_8 or stage_9
    if not has_subject and not has_stage: return []
    if has_stage and not has_subject: is_math = is_sci = is_eng = True
    if has_subject and not has_stage: stage_8 = True

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

# -----------------------------
# 12) RENDER CHAT
# -----------------------------
if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()

# ASSIGNMENT BANNER (for logged-in students)
if is_authenticated and user_role == "student" and db is not None:
    pending_assignments = db.collection("users").document(auth_object.email).collection("assignments").where(
        filter=firestore.FieldFilter("status", "==", "pending")
    ).stream()
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
                        assign_msg = {
                            "role": "assistant",
                            "content": a_data.get("content", ""),
                            "is_downloadable": True,
                            "images": [],
                            "is_assignment": True,
                        }
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
                if img_bytes:
                    st.image(img_bytes, use_container_width=True, output_format="PNG", caption="✨ Generated by helix.ai")
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
                st.download_button(
                    label="📥 Download Question Paper as PDF",
                    data=pdf_buffer,
                    file_name=f"Helix_Question_Paper_{idx}.pdf",
                    mime="application/pdf",
                    key=f"download_{st.session_state.current_thread_id}_{idx}",
                )
            except Exception: pass

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
            if "image" in (file_mime or ""): st.image(file_bytes, width=320)
            elif "pdf" in (file_mime or ""): st.caption(f"📄 *Attached: {file_name}*")
            elif "text/plain" in (file_mime or "") or (file_name or "").endswith(".txt"): st.caption(f"📝 *Attached: {file_name}*")

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()
        try:
            has_attachment = file_bytes is not None
            relevant_books = select_relevant_books(
                prompt + " science stage 8" if has_attachment else prompt,
                st.session_state.textbook_handles
            )

            if relevant_books:
                book_names = [get_friendly_name(b.display_name) for b in relevant_books]
                st.caption(f"🔍 *Scanning Curriculum: {', '.join(book_names)}*")
            else:
                st.caption("🔍 *Analyzing attached file...*" if has_attachment else "⚡ *Quick reply (General Knowledge)*")

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

            current_prompt_parts.append(types.Part.from_text(
                text=f"Please read the user query and look at attached files. Check Cambridge textbooks for accuracy if provided.\n\nQuery: {prompt}"
            ))
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
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3,
                    tools=[{"google_search": {}}],
                ),
            )

            bot_text = safe_response_text(text_response)
            if not bot_text.strip():
                bot_text = "⚠️ *Helix couldn't generate a text response this time.* Try rephrasing your question."

            # EXTRACT HIDDEN ANALYTICS
            analytics_match = re.search(r"\[ANALYTICS:\s*({.*?})\s*\]", bot_text, flags=re.IGNORECASE | re.DOTALL)
            if analytics_match:
                try:
                    analytics_data = json.loads(analytics_match.group(1))
                    bot_text = bot_text[:analytics_match.start()].strip()
                    if is_authenticated and db is not None:
                        db.collection("users").document(auth_object.email).collection("analytics").add({
                            "timestamp": time.time(),
                            "topic": analytics_data.get("topic", "General"),
                            "understanding_level": analytics_data.get("understanding_level", "Unknown"),
                            "weak_point": analytics_data.get("weak_point", "None"),
                            "question_asked": analytics_data.get("question_asked", "None")
                        })
                except Exception as e:
                    print(f"Analytics extraction error: {e}")

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
                for img in generated_images:
                    if img is None:
                        bot_text += "\n\n⚠️ *Helix tried to draw a diagram here, but the image generator is currently overloaded. Please try again later.*"

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
                if "temp_pdf_path" in locals() and temp_pdf_path and os.path.exists(temp_pdf_path):
                    os.remove(temp_pdf_path)
            except Exception: pass
