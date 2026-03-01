import streamlit as st
import os
import time
import re
import concurrent.futures
from pathlib import Path
from io import BytesIO

from google import genai
from google.genai import types

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
# 2) THEME CSS & TITLE
# -----------------------------
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
<div class="big-title">📚 helix.ai</div>
<div class="subtitle">Your CIE Tutor for Grade 6-8!</div>
""", unsafe_allow_html=True)


# -----------------------------
# 3) HELPERS
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


def safe_response_text(resp) -> str:
    """
    Make bot_text ALWAYS a string (never None), even when the model returns no text.
    Also handles cases where resp.text raises.
    """
    # 1) Fast path
    try:
        t = getattr(resp, "text", None)
        if t:
            return str(t)
    except Exception:
        pass

    # 2) Fallback: candidates -> content.parts -> text
    try:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            content = getattr(cands[0], "content", None)
            parts = getattr(content, "parts", None) or []
            texts = []
            for p in parts:
                tx = getattr(p, "text", None)
                if tx:
                    texts.append(tx)
            if texts:
                return "\n".join(texts)
    except Exception:
        pass

    return ""


def md_inline_to_rl(text: str) -> str:
    """
    Minimal Markdown-ish to ReportLab Paragraph markup:
    - Escapes &,<,>
    - **bold** -> <b>bold</b>
    - *italics* -> <i>italics</i>  (simple; avoids underscores)
    """
    if text is None:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Bold: **...**
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)

    # Italic: *...* (avoid converting list bullets like "* item" by requiring non-space after first *)
    s = re.sub(r"(?<!\*)\*(\S.+?)\*(?!\*)", r"<i>\1</i>", s)

    return s


# -----------------------------
# 4) VISUAL GENERATORS
# -----------------------------
def generate_single_image(desc: str):
    """Generates a single diagram image via Gemini image model."""
    try:
        img_resp = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[desc],
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in (img_resp.parts or []):
            if getattr(part, "inline_data", None):
                return part.inline_data.data
    except Exception as e:
        print(f"Image gen error: {e}")
    return None


def generate_pie_chart(data_str: str):
    """Generates a pie chart PNG bytes using Matplotlib (no AI)."""
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
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            startangle=140,
            colors=theme_colors[: len(labels)],
            textprops={"color": "black", "fontsize": 9},
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
# 5) PDF EXPORT (supports Markdown tables + visuals)
# -----------------------------
def create_pdf(content: str, images=None, filename="Question_Paper.pdf"):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#00d4ff"),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=14,
        spaceAfter=10,
        spaceBefore=10,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["BodyText"],
        fontSize=11,
        spaceAfter=8,
        alignment=TA_LEFT,
        fontName="Helvetica",
    )

    story = []
    if not content:
        content = "⚠️ No content to export."

    lines = str(content).split("\n")

    # Strip AI preamble safely (look for first markdown header in first 5 lines)
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

        # Remove inline "(Source: ...)" remnants if present
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

        available_width = doc.width
        col_width = available_width / max(1, ncols)
        col_widths = [col_width] * ncols

        t = Table(norm_rows, colWidths=col_widths)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00d4ff")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 0.18 * inch))
        table_rows = []

    for raw in cleaned_lines:
        line = raw.rstrip("\n")
        s = line.strip()

        # Markdown table detection: lines like | a | b |
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.split("|")[1:-1]]
            # Skip separator rows: | --- | :---: |
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            table_rows.append(cells)
            continue
        else:
            render_pending_table()

        if not s:
            story.append(Spacer(1, 0.14 * inch))
            continue

        # Visual placeholder lines; images[] index must match triggers order
        if s.startswith("IMAGE_GEN:") or s.startswith("PIE_CHART:"):
            if images and img_idx < len(images) and images[img_idx]:
                try:
                    img_stream = BytesIO(images[img_idx])
                    rl_reader = ImageReader(img_stream)
                    iw, ih = rl_reader.getSize()
                    aspect = ih / float(iw)
                    target_width = 4.6 * inch
                    target_height = target_width * aspect
                    story.append(Spacer(1, 0.12 * inch))
                    story.append(RLImage(img_stream, width=target_width, height=target_height))
                    story.append(Spacer(1, 0.12 * inch))
                except Exception:
                    pass
            img_idx += 1
            continue

        # Page break before mark scheme title if it's a header
        if "mark scheme" in s.lower() and s.startswith("#"):
            story.append(PageBreak())
            text = re.sub(r"^#+\s*", "", s)
            story.append(Paragraph(md_inline_to_rl(text), title_style))
            continue

        # Render headings / normal paragraphs
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
# 6) SYSTEM INSTRUCTION
# -----------------------------
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

### RULE 1: THE VISION & RAG SEARCH (CRITICAL)
- If the user provides an IMAGE, PDF, or TXT file, analyze it carefully.
- STEP 1: Search the attached PDF textbooks using OCR FIRST. Cite the book at the end like this: (Source: Cambridge Science Textbook 7).
- STEP 2: If the textbooks do not contain the answer, explicitly state: "I couldn't find this in your textbook, but here is what I found:"

### RULE 2: CONVERSATION MEMORY
- Build upon previous responses if the user asks for more details.

### RULE 4: STAGE 9 ENGLISH TB/WB I couldn't find the textbooks and workbooks for Stage 9 English, so here is a table of contents that you will refer to when answering a query for that chapter: Chapter 1 • Writing to explore and reflect 1.1 What is travel writing?  1.2 Selecting and noting key information in travel texts  1.3 Comparing tone and register in travel texts  1.4 Responding to travel writing  1.5 Understanding grammatical choices in travel writing  1.6 Varying sentences for effect  1.7 Boost your vocabulary  1.8 Creating a travel account  Chapter 2 • Writing to inform and explain 2.1 Matching informative texts to audience and purpose  2.2 Using formal and informal language in information texts  2.3 Comparing information texts  2.4 Using discussion to prepare for a written assignment  2.5 Planning information texts to suit different audiences  2.6 Shaping paragraphs to suit audience and purpose  2.7 Crafting sentences for a range of effects  2.8 Making explanations precise and concise  2.9 Writing encyclopedia entries  Chapter 3 • Writing to argue and persuade 3.1 Reviewing persuasive techniques  3.2 Commenting on use of language to persuade  3.3 Exploring layers of persuasive language  3.4 Responding to the use of persuasive language  3.5 Adapting grammar choices to create effects in argument writing  3.6 Organising a whole argument effectively  3.7 Organising an argument within each paragraph  3.8 Presenting and responding to a question  3.9 Producing an argumentative essay  Chapter 4 • Descriptive writing 4.1 Analysing how atmospheres are created  4.2 Developing analysis of a description  4.3 Analysing atmospheric descriptions  4.4 Using images to inspire description  4.5 Using language to develop an atmosphere  4.6 Sustaining a cohesive atmosphere  4.7 Creating atmosphere through punctuation  4.8 Using structural devices to build up atmosphere  4.9 Producing a powerful description  Chapter 5 • Narrative writing 5.1 Understanding story openings  5.2 Exploring setting and atmosphere  5.3 Introducing characters in stories  5.4 Responding to powerful narrative  5.5 Pitching a story  5.6 Creating narrative suspense and climax  5.7 Creating character  5.8 Using tenses in narrative  5.9 Using pronouns and sentence order for effect  5.10 Creating a thriller  Chapter 6 • Writing to analyse and compare 6.1 Analysing implicit meaning in non-fiction texts  6.2 Analysing how a play's key elements create different effects  6.3 Using discussion skills to analyse carefully  6.4 Comparing effectively through punctuation and grammar  6.5 Analysing two texts  Chapter 7 • Testing your skills 7.1 Reading and writing questions on non-fiction texts  7.2 Reading and writing questions on fiction texts  7.3 Assessing your progress: non-fiction reading and writing  7.4 Assessing your progress: fiction reading and writing

### RULE 3: QUESTION PAPERS (CRITICAL FORMATTING)
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
# 7) GOOGLE FILE API (upload textbooks once)
# -----------------------------
@st.cache_resource(show_spinner=False)
def upload_textbooks():
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
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

        # Reuse if already ACTIVE on server
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
                config={"mime_type": "application/pdf", "display_name": found_path.name},
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
# 8) ROUTING: pick relevant books
# -----------------------------
def select_relevant_books(query, file_dict):
    q = (query or "").lower()
    selected = []

    is_math = any(k in q for k in ["math", "algebra", "geometry", "calculate", "equation"])
    is_sci = any(k in q for k in ["science", "cell", "biology", "physics", "chemistry"])
    is_eng = any(k in q for k in ["english", "poem", "story", "essay", "writing"])
    if not is_math and not is_sci and not is_eng:
        is_sci = True

    stage_7 = any(k in q for k in ["stage 7", "grade 6"])
    stage_8 = any(k in q for k in ["stage 8", "grade 7"])
    stage_9 = any(k in q for k in ["stage 9", "grade 8"])
    has_stage = stage_7 or stage_8 or stage_9

    def add_books(subject_key, active):
        if not active:
            return
        for book in file_dict.get(subject_key, []):
            name = (book.display_name or "").lower()
            if has_stage:
                if stage_7 and "cie_7" in name:
                    selected.append(book)
                if stage_8 and "cie_8" in name:
                    selected.append(book)
                if stage_9 and "cie_9" in name:
                    selected.append(book)
            else:
                if "cie_8" in name:
                    selected.append(book)

    add_books("math", is_math)
    add_books("sci", is_sci)
    add_books("eng", is_eng)

    return selected[:3]


# -----------------------------
# 9) SESSION INIT
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 **Hey there! I'm Helix!**\n\n"
                "I'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\n"
                "I can answer your doubts, draw diagrams, and create quizzes!\n"
                "You can also **attach photos, PDFs, or text files directly in the chat box below!** 📸📄\n\n"
                "**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n"
                "*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\n"
                "What are we learning today?"
            ),
            "is_greeting": True,
        }
    ]

if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()


# -----------------------------
# 10) DISPLAY CHAT HISTORY
# -----------------------------
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
                    key=f"download_{idx}",
                )
            except Exception:
                pass


# -----------------------------
# 11) MAIN LOOP (chat + upload)
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
            relevant_books = select_relevant_books(prompt, st.session_state.textbook_handles)

            if relevant_books:
                book_names = [get_friendly_name(b.display_name) for b in relevant_books]
                st.caption(f"🔍 *Scanning Curriculum: {', '.join(book_names)}*")
            else:
                st.caption("🔍 *Scanning generalized database.*")

            thinking_placeholder.markdown("""
                <div class="thinking-container">
                    <span class="thinking-text">🧠 Reading & Looking...</span>
                    <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
                </div>
            """, unsafe_allow_html=True)

            current_prompt_parts = []

            # Attach user file (if any)
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
                    current_prompt_parts.append(
                        types.Part.from_text(
                            text=f"--- Attached Text File ({file_name}) ---\n{raw_text}\n--- End of File ---\n"
                        )
                    )

            # Attach relevant textbooks
            for book in relevant_books:
                friendly = get_friendly_name(book.display_name)
                current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly}]"))
                current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))

            enhanced_prompt = (
                "Please read the user query and look at attached files (if provided). "
                "Check the attached Cambridge textbooks for syllabus accuracy.\n\n"
                f"Query: {prompt}"
            )
            current_prompt_parts.append(types.Part.from_text(text=enhanced_prompt))
            current_content = types.Content(role="user", parts=current_prompt_parts)

            # Short history (text only)
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
                bot_text = (
                    "⚠️ *Helix couldn't generate a text response this time (it may have been blocked or returned no text).* "
                    "Try rephrasing your question."
                )

            thinking_placeholder.empty()

            # Find visuals in order
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

            is_downloadable = "[PDF_READY]" in bot_text

            bot_msg = {
                "role": "assistant",
                "content": bot_text,
                "is_downloadable": is_downloadable,
                "images": generated_images,
            }
            st.session_state.messages.append(bot_msg)

            display_text = bot_text.replace("[PDF_READY]", "").strip()
            st.markdown(display_text)

            for img in generated_images:
                if img:
                    st.image(img, caption="Generated Visual")

            if is_downloadable:
                try:
                    pdf_buffer = create_pdf(bot_text, images=generated_images)
                    st.download_button(
                        label="📥 Download Question Paper as PDF",
                        data=pdf_buffer,
                        file_name=f"Helix_Question_Paper_{len(st.session_state.messages)}.pdf",
                        mime="application/pdf",
                        key="download_current",
                    )
                except Exception as pdf_err:
                    st.error(f"Could not generate PDF: {pdf_err}")

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")

        finally:
            # cleanup temp pdf file if created
            try:
                if "temp_pdf_path" in locals() and temp_pdf_path and os.path.exists(temp_pdf_path):
                    os.remove(temp_pdf_path)
            except Exception:
                pass

