import streamlit as st
import os
import time
import re
from pathlib import Path
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image as RLImage
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO

# --- 1. SETUP & CONFIGURATION ---
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

# --- 2. THEME CSS & TITLE ---
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

# --- 3. HELPER: FORMAT FILE NAMES ---
def get_friendly_name(filename):
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

# --- 4. PDF EXPORT FUNCTION (NOW SUPPORTS EMBEDDED IMAGES!) ---
def create_pdf(content, images=None, filename="Question_Paper.pdf"):
    """Convert markdown-style text and generated images to a clean PDF"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=0.75*inch, leftMargin=0.75*inch, topMargin=0.75*inch, bottomMargin=0.75*inch)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, textColor='#00d4ff', spaceAfter=12, alignment=TA_CENTER, fontName='Helvetica-Bold')
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=14, spaceAfter=10, spaceBefore=10, fontName='Helvetica-Bold')
    body_style = ParagraphStyle('CustomBody', parent=styles['BodyText'], fontSize=11, spaceAfter=8, alignment=TA_LEFT, fontName='Helvetica')
    
    story = []
    
    lines = content.split('\n')
    start_index = 0
    
    # Strip AI preamble
    for i, line in enumerate(lines):
        if line.strip().startswith('#'):
            start_index = i
            break
            
    lines = lines[start_index:]
    
    cleaned_lines = []
    skip_section = False
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Source(s):") or stripped.startswith("**Source(s):**"):
            skip_section = True
            continue
        if skip_section:
            if not stripped or stripped.startswith("*") or stripped.startswith("-"):
                continue
            else:
                skip_section = False
        
        clean_line = re.sub(r'\s*\(Source:.*?\)', '', line)
        clean_line = re.sub(r'^\s*\*\s+', '', clean_line)
        cleaned_lines.append(clean_line)
    
    img_idx = 0
    for line in cleaned_lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            story.append(Spacer(1, 0.15*inch))
            continue
            
        # --- NEW: IMAGE INJECTION INTO PDF ---
        if "IMAGE_GEN:" in line_stripped:
            if images and img_idx < len(images):
                try:
                    img_stream = BytesIO(images[img_idx])
                    rl_reader = ImageReader(img_stream)
                    iw, ih = rl_reader.getSize()
                    aspect = ih / float(iw)
                    target_width = 5.0 * inch
                    target_height = target_width * aspect
                    story.append(Spacer(1, 0.15*inch))
                    story.append(RLImage(img_stream, width=target_width, height=target_height))
                    story.append(Spacer(1, 0.15*inch))
                except Exception:
                    pass
                img_idx += 1
            continue
            
        if "mark scheme" in line_stripped.lower() and line_stripped.startswith('#'):
            story.append(PageBreak())
            text = re.sub(r'^#+\s*', '', line_stripped)
            story.append(Paragraph(text, title_style))
            continue
            
        line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        line = re.sub(r'(?<!\w)(?:_|\*)(.*?)(?:_|\*)(?!\w)', r'<i>\1</i>', line)
        
        if line.startswith('# '):
            text = line.replace('# ', '', 1).strip()
            story.append(Paragraph(text, title_style))
        elif line.startswith('## '):
            text = line.replace('## ', '', 1).strip()
            story.append(Paragraph(text, heading_style))
        elif line.startswith('### '):
            text = line.replace('### ', '', 1).strip()
            para = Paragraph(f"<b>{text}</b>", body_style)
            story.append(para)
        else:
            story.append(Paragraph(line, body_style))
    
    story.append(Spacer(1, 0.3*inch))
    footer = Paragraph("<i>Generated by helix.ai - Your CIE Tutor</i>", body_style)
    story.append(footer)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 5. SYSTEM INSTRUCTIONS (HIGHLY OPTIMIZED) ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

### RULE 1: THE VISION & RAG SEARCH (CRITICAL)
- If the user provides an IMAGE, PDF, or TXT file, analyze it carefully.
- STEP 1: Search the attached PDF textbooks using OCR FIRST. Cite the book at the end like this: (Source: Cambridge Science Textbook 7).
- STEP 2: If the textbooks do not contain the answer, explicitly state: "I couldn't find this in your textbook, but here is what I found:"

### RULE 2: CONVERSATION MEMORY
- Build upon previous responses if the user asks for more details.

### RULE 3: QUESTION PAPERS (CRITICAL FORMATTING)
- DO NOT use Markdown tables (e.g. `| Property | Metal |`). Text tables will not render properly.
- If a question requires a table, you MUST generate it as an image using the IMAGE_GEN command. Example: `IMAGE_GEN: [A clean, blank comparison table worksheet for metals and non-metals]`
- MUST include visual, diagram-based questions. Generate the diagrams using the IMAGE_GEN command. Example: `IMAGE_GEN: [Detailed diagram of a plant cell, with clear label lines A, B, C for a science exam]`
- NUMBERING: Keep numbering extremely clean and sequential (1., 2., 3.) and sub-questions as (a), (b), (c).
- MARKS: Put the marks on the SAME LINE as the question text at the very end (e.g., "Describe the process of photosynthesis. [3]"), do NOT put marks on a new line.
- CITATION RULE: List the source(s) ONLY ONCE at the very bottom of the entire paper.

### RULE 4: STAGE 9 ENGLISH TB/WB
- Table of contents: Chapter 1-7 covers Writing to explore, inform, argue, descriptive, narrative, analyze.

### RULE 5: IMAGE GENERATION SYNTAX (STRICT)
- To trigger image generation, output this EXACT command on its OWN NEW LINE:
  IMAGE_GEN: [Detailed description of the image, educational, white background]
- You can use MULTIPLE IMAGE_GEN commands throughout the paper for different tables and diagrams!

### RULE 6: MARK SCHEME
- Put "## Mark Scheme" at the very bottom of the test. Do not use citation tags inside the mark scheme.

### RULE 7: ARMAAN STYLE
- If asked for "Armaan Style", explain in expert terms using complex vocabulary.
"""

# --- 6. GOOGLE FILE API ---
@st.cache_resource(show_spinner=False)
def upload_textbooks():
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
    ]
    active_files = {"sci": [], "math": [], "eng": []}
    
    msg_placeholder = st.empty()
    with msg_placeholder.chat_message("assistant"):
        st.markdown(f"""
        <div class="thinking-container">
            <span class="thinking-text">🔄 Connecting to Google Cloud & Scanning Library...</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

    existing_server_files = {f.display_name.lower(): f for f in client.files.list() if f.display_name}
    pdf_map = {p.name.lower(): p for p in Path.cwd().rglob("*.pdf")}

    for target_name in target_filenames:
        t_lower = target_name.lower()
        if t_lower in existing_server_files:
            server_file = existing_server_files[t_lower]
            if server_file.state.name == "ACTIVE":
                if "sci" in t_lower: active_files["sci"].append(server_file)
                elif "math" in t_lower: active_files["math"].append(server_file)
                elif "eng" in t_lower: active_files["eng"].append(server_file)
                continue

        found_path = pdf_map.get(t_lower)
        if found_path:
            try:
                uploaded_file = client.files.upload(file=str(found_path), config={'mime_type': 'application/pdf', 'display_name': found_path.name})
                start_time = time.time()
                while uploaded_file.state.name == "PROCESSING":
                    if time.time() - start_time > 180: break
                    time.sleep(3)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                
                if uploaded_file.state.name == "ACTIVE":
                    if "sci" in t_lower: active_files["sci"].append(uploaded_file)
                    elif "math" in t_lower: active_files["math"].append(uploaded_file)
                    elif "eng" in t_lower: active_files["eng"].append(uploaded_file)
            except Exception:
                continue

    msg_placeholder.empty()
    return active_files

# --- 7. STRICT ROUTING LOGIC ---
def select_relevant_books(query, file_dict):
    query = query.lower()
    selected = []
    is_math = any(k in query for k in ["math", "algebra", "geometry", "calculate", "equation"])
    is_sci = any(k in query for k in ["science", "cell", "biology", "physics", "chemistry"])
    is_eng = any(k in query for k in ["english", "poem", "story", "essay", "writing"])
    if not is_math and not is_sci and not is_eng: is_sci = True
    stage_7 = any(k in query for k in ["stage 7", "grade 6"])
    stage_8 = any(k in query for k in ["stage 8", "grade 7"])
    stage_9 = any(k in query for k in ["stage 9", "grade 8"])
    has_stage = stage_7 or stage_8 or stage_9

    def add_books(subject_key, is_active):
        if not is_active: return
        for book in file_dict.get(subject_key, []):
            name = (book.display_name or "").lower()
            if has_stage:
                if stage_7 and "cie_7" in name: selected.append(book)
                if stage_8 and "cie_8" in name: selected.append(book)
                if stage_9 and "cie_9" in name: selected.append(book)
            else:
                if "cie_8" in name: selected.append(book)

    add_books("math", is_math)
    add_books("sci", is_sci)
    add_books("eng", is_eng)
    return selected[:3] 

# --- 8. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizes! You can also **attach photos, PDFs, or Text files directly in the chat box below!** 📸📄\n\n**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\nWhat are we learning today?",
            "is_greeting": True
        }
    ]

if "textbook_handles" not in st.session_state:
    st.session_state.textbook_handles = upload_textbooks()

# --- 9. DISPLAY CHAT ---
for idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        # Display AI generated images inside the flow!
        if message.get("images"):
            for img_bytes in message["images"]:
                st.image(img_bytes, width=400)
        
        # Re-render any attachments the user sent previously
        if message.get("user_attachment_bytes"):
            mime = message.get("user_attachment_mime", "")
            name = message.get("user_attachment_name", "File")
            if "image" in mime:
                st.image(message["user_attachment_bytes"], width=300)
            elif "pdf" in mime:
                st.caption(f"📄 *Attached PDF Document: {name}*")
            elif "text" in mime or name.endswith(".txt"):
                st.caption(f"📝 *Attached Text Document: {name}*")
        
        # PDF Download Button
        if message["role"] == "assistant" and message.get("is_downloadable"):
            try:
                pdf_buffer = create_pdf(message["content"], images=message.get("images", []))
                st.download_button(
                    label="📥 Download Question Paper as PDF",
                    data=pdf_buffer,
                    file_name=f"Helix_Question_Paper_{idx}.pdf",
                    mime="application/pdf",
                    key=f"download_{idx}"
                )
            except Exception:
                pass

# --- 10. MAIN LOOP WITH INTEGRATED CHAT UPLOADER ---
if chat_input_data := st.chat_input("Ask Helix... (Click the paperclip to upload a file!)", accept_file=True, file_type=["jpg", "jpeg", "png", "webp", "avif", "svg", "pdf", "txt"]):
    
    prompt = chat_input_data.text
    uploaded_files = chat_input_data.files
    user_msg_dict = {"role": "user", "content": prompt}
    
    file_bytes, file_mime, file_name = None, None, None
    if uploaded_files and len(uploaded_files) > 0:
        file_bytes = uploaded_files[0].getvalue()
        file_mime = uploaded_files[0].type
        file_name = uploaded_files[0].name
        user_msg_dict["user_attachment_bytes"] = file_bytes
        user_msg_dict["user_attachment_mime"] = file_mime
        user_msg_dict["user_attachment_name"] = file_name
        
    st.session_state.messages.append(user_msg_dict)
    
    with st.chat_message("user"):
        st.markdown(prompt)
        if file_bytes:
            if "image" in file_mime: st.image(file_bytes, width=300)
            elif "pdf" in file_mime: st.caption(f"📄 *Attached: {file_name}*")
            elif "text/plain" in file_mime or file_name.endswith(".txt"): st.caption(f"📝 *Attached: {file_name}*")

    with st.chat_message("assistant"):
        try:
            relevant_books = select_relevant_books(prompt, st.session_state.textbook_handles)
            
            if relevant_books:
                book_names = [get_friendly_name(b.display_name) for b in relevant_books]
                st.caption(f"🔍 *Scanning Curriculum: {', '.join(book_names)}*")
            else:
                st.caption("🔍 *Scanning generalized database.*")

            thinking_placeholder = st.empty()
            thinking_placeholder.markdown(f"""
                <div class="thinking-container">
                    <span class="thinking-text">🧠 Reading & Looking...</span>
                    <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
                </div>
            """, unsafe_allow_html=True)
            
            current_prompt_parts = []
            
            if file_bytes:
                if "image" in file_mime:
                    current_prompt_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime))
                elif "pdf" in file_mime:
                    temp_pdf_path = f"temp_user_upload_{int(time.time())}.pdf"
                    with open(temp_pdf_path, "wb") as f:
                        f.write(file_bytes)
                    user_uploaded_pdf = client.files.upload(file=temp_pdf_path)
                    while user_uploaded_pdf.state.name == "PROCESSING":
                        time.sleep(1)
                        user_uploaded_pdf = client.files.get(name=user_uploaded_pdf.name)
                    current_prompt_parts.append(types.Part.from_uri(file_uri=user_uploaded_pdf.uri, mime_type="application/pdf"))
                elif "text/plain" in file_mime or file_name.endswith(".txt"):
                    raw_text = file_bytes.decode("utf-8", errors="ignore")
                    current_prompt_parts.append(types.Part.from_text(text=f"--- Attached Text File ({file_name}) ---\n{raw_text}\n--- End of File ---\n"))
            
            for book in relevant_books:
                friendly_name = get_friendly_name(book.display_name)
                current_prompt_parts.append(types.Part.from_text(text=f"[Source Document: {friendly_name}]"))
                current_prompt_parts.append(types.Part.from_uri(file_uri=book.uri, mime_type="application/pdf"))
            
            enhanced_prompt = f"Please read the user query and look at the attached files (if provided). Check the attached Cambridge textbooks for syllabus accuracy.\n\nQuery: {prompt}"
            current_prompt_parts.append(types.Part.from_text(text=enhanced_prompt))
            
            current_content = types.Content(role="user", parts=current_prompt_parts)
            
            history_contents = []
            text_msgs = [m for m in st.session_state.messages[:-1] if not m.get("is_greeting")]
            for msg in text_msgs[-7:]:
                history_contents.append(types.Content(role="user" if msg["role"] == "user" else "model", parts=[types.Part.from_text(text=msg["content"])]))
            
            full_contents = history_contents + [current_content]

            text_response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=full_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.3, 
                    tools=[{"google_search": {}}]
                )
            )
            
            bot_text = text_response.text
            thinking_placeholder.empty()

            # --- MASSIVE NEW FEATURE: GENERATING MULTIPLE IMAGES ---
            img_prompts = re.findall(r'IMAGE_GEN:\s*\[(.*?)\]', bot_text)
            generated_images = []
            
            if img_prompts:
                img_thinking = st.empty()
                img_thinking.markdown("*🖌️ Painting diagrams & tables for the exam...*")
                for desc in img_prompts:
                    try:
                        img_resp = client.models.generate_content(
                            model="gemini-3-pro-image-preview",
                            contents=[desc],
                            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'])
                        )
                        for part in img_resp.parts:
                            if part.inline_data:
                                generated_images.append(part.inline_data.data)
                    except Exception:
                        pass
                img_thinking.empty()

            is_downloadable = any(keyword in bot_text.lower() for keyword in ["question paper", "quiz", "test", "assessment", "exam", "mark scheme"])
            
            bot_msg = {
                "role": "assistant", 
                "content": bot_text, 
                "is_downloadable": is_downloadable,
                "images": generated_images
            }
            st.session_state.messages.append(bot_msg)
            
            # Show on screen instantly
            st.markdown(bot_text)
            for img in generated_images:
                st.image(img, caption="Generated by Helix")
            
            # Generate the supercharged PDF with images embedded!
            if is_downloadable:
                try:
                    pdf_buffer = create_pdf(bot_text, images=generated_images)
                    st.download_button(
                        label="📥 Download Question Paper as PDF",
                        data=pdf_buffer,
                        file_name=f"Helix_Question_Paper_{len(st.session_state.messages)}.pdf",
                        mime="application/pdf",
                        key=f"download_current"
                    )
                except Exception as pdf_err:
                    st.error(f"Could not generate PDF: {pdf_err}")

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")
