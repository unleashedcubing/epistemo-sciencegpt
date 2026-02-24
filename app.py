__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import streamlit as st
import os
import time
import re
import random
import gc
from pathlib import Path

from google import genai
from google.genai import types

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import chromadb

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- 2. API CLIENT SETUP ---
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

# --- 3. THEME CSS & STATUS INDICATOR ---
st.markdown("""
<style>
.stApp {
  background:
    radial-gradient(800px circle at 50% 0%, rgba(0, 212, 255, 0.08), rgba(0, 212, 255, 0.00) 60%),
    var(--background-color);
  color: var(--text-color);
}
.status-indicator {
  position: fixed; top: 60px; left: 15px; display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background-color: rgba(30, 30, 30, 0.8); border-radius: 20px;
  backdrop-filter: blur(8px); z-index: 100000; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
  border: 1px solid rgba(255,255,255,0.1); transition: all 0.3s ease;
}
.book-icon { font-size: 24px; }
.spinner {
  width: 18px; height: 18px; border: 3px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%; border-top-color: #00d4ff; animation: spin 1s ease-in-out infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.status-loading { border-color: #ff4b4b; }
.status-loading .book-icon { animation: pulse-red 1.5s infinite; }
.status-ready { border-color: #00c04b; background-color: rgba(0, 192, 75, 0.15); }
.status-error { border-color: #ffa500; }
@keyframes pulse-red {
  0% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.1); opacity: 0.7; }
  100% { transform: scale(1); opacity: 1; }
}
.big-title {
  font-family: 'Inter', sans-serif; color: #00d4ff; text-align: center;
  font-size: 48px; font-weight: 1200; letter-spacing: -3px; margin-bottom: 0px;
  text-shadow: 0 0 6px rgba(0, 212, 255, 0.55); animation: helix-glow 2.2s ease-in-out infinite;
}
@keyframes helix-glow {
  0%, 100% { text-shadow: 0 0 6px rgba(0, 212, 255, 0.45); }
  50% { text-shadow: 0 0 8px rgba(0, 212, 255, 0.75); }
}
.subtitle { text-align: center; color: var(--text-color); opacity: 0.60; font-size: 18px; margin-bottom: 30px; }
.thinking-container {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px;
  background-color: var(--secondary-background-color); border-radius: 8px; margin: 10px 0; border-left: 3px solid #fc8404;
}
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot {
  width: 6px; height: 6px; border-radius: 50%; background-color: #fc8404;
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

# --- 4. SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, a friendly CIE Science/Math/English Tutor for Stage 7-9 students.

***REMEMBER VERY IMPORTANT!!!!!: The moment you recieve the user prompt, wait 4 seconds and read the prompt fully. If you are 90% sure that the user's query is not related to the book sources, don't bother checking the books, answer based on internet/your own way. If you aren't sure, check the books.***

IMPORTANT: Make sure to make questions based on stage and chapter (if chapter is given)
ALSO: The textbooks were too big, so I split each into 2. The names would have ..._1.pdf or ..._2.pdf. The ... area would have the year. Check both when queries come up.
ALSO: In MCQs, randomize the answers. REMEMBER, RANDOMIZE MCQ ANSWERS.
ALSO: Use BOTH WB (Workbook) AND TB (Textbook) because the WB has questions mainly, but SB has theory. Using BOTH WILL GIVE YOU A WIDE RANGE OF QUESTIONS.
ALSO: DO NOT INTRODUCE YOURSELF LIKE "I am Helix!" as I have already created an introduction message. Just get to the user's query immediately.

### RULE 1: BE SEAMLESS AND NATURAL
- ALWAYS prioritize the retrieved RAG PDF chunks to answer the question, but act as if you just know the information natively.
- NEVER use phrases like "According to the excerpts", "I couldn't find this in the book", "The materials provided", or mention PDF filenames.
- If the provided context is empty or irrelevant, seamlessly answer the question using your general knowledge without apologizing or mentioning the missing context.
- If the user asks about "Chapter 8" but the context seems confusing or mixed up across different subjects (e.g., math and science combined), politely ask them: "Are we looking at Science, Math, or English right now?"

### RULE 2: STAGE 9 ENGLISH TB/WB: ***IMPORTANT, VERY***
- I couldn't find the TB/WB source for Stage 9 English, so you will go off of this table of contents:
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

### RULE 3: IMAGE GENERATION (STRICT)
- **IF THE USER ASKS FOR A NORMAL DIAGRAM:** If they just ask for a "diagram of a cell" or "picture of a heart", or a infographic or mindmap, or a mind map for math, you MUST output this specific command and nothing else:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]

### RULE 4: QUESTION PAPERS
- When asked to create a question paper, quiz, or test, strictly follow this structure:
  - Science (Checkpoint style): produce Paper 1 and/or Paper 2 (default both) as a 50‑mark, ~45‑minute structured written paper with numbered questions showing marks like "(3)".
  - Mathematics (Checkpoint style): produce Paper 1 non‑calculator and Paper 2 calculator (default both), each ~45 minutes and 50 marks.
  - English (Checkpoint style): produce Paper 1 Non‑fiction and Paper 2 Fiction (default both), each ~45 minutes and 50 marks.

### RULE 5: ARMAAN STYLE
If a user asks you to reply in Armaan Style, you have to explain in expert physicist/chemist/biologist/mathematician/writer terms, with difficult out of textbook sources. You can then simple it down if the user wishes.
"""

# --- 5. ROBUST FILE LIST ---
TARGET_FILENAMES = [
    "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
    "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
    "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
    "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
    "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
]

def parse_filename_metadata(filename: str):
    name = filename.lower()
    stage = None
    m_stage = re.search(r"cie_(\d)_", name)
    if m_stage: stage = int(m_stage.group(1))

    book = None
    if "_sb_" in name: book = "SB"
    if "_wb_" in name: book = "WB"

    subject = None
    if "sci" in name: subject = "sci"
    elif "math" in name: subject = "math"
    elif "eng" in name: subject = "eng"

    is_answers = "answers" in name

    return {
        "stage": stage,
        "book": book,
        "subject": subject,
        "is_answers": is_answers,
        "filename": filename
    }

# --- 6. SMART FILTERS WITH MEMORY ---
def infer_subject(history_text: str):
    q = history_text.lower()
    math_keywords = ["math", "algebra", "geometry", "calculate", "equation", "number", "fraction", "maths", "arithmetic", "probability"]
    sci_keywords = ["science", "cell", "biology", "physics", "chemistry", "atom", "energy", "force", "organism", "photosynthesis", "respiration", "compound"]
    eng_keywords = ["english", "poem", "story", "essay", "writing", "grammar", "text", "author", "travel writing", "noun", "verb", "comprehension"]
    if any(k in q for k in math_keywords): return "math"
    if any(k in q for k in sci_keywords): return "sci"
    if any(k in q for k in eng_keywords): return "eng"
    return None

def infer_stage(history_text: str):
    q = history_text.lower()
    m_stage = re.search(r"\bstage\s*([789])\b|\b([789])(?:th)?\s*stage\b", q)
    if m_stage: return int(m_stage.group(1) or m_stage.group(2))
    m_grade = re.search(r"\b(?:grade|year)\s*([678])\b|\b([678])(?:th)?\s*(?:grade|year)\b", q)
    if m_grade: return int(m_grade.group(1) or m_grade.group(2)) + 1
    return None

# --- 7. RAG: IN-MEMORY ENGINE WITH ADAPTIVE HIGH-SPEED INGESTION ---
@st.cache_resource(show_spinner=False)
def get_vector_db():
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/text-embedding-004",
        google_api_key=api_key
    )

    client = chromadb.EphemeralClient()
    collection_name = "helix_collection"

    # Setup UI
    status_placeholder = st.empty()
    status_placeholder.markdown("""
        <div class="status-indicator status-loading">
            <span class="book-icon">📕</span>
            <div class="spinner"></div>
        </div>
        """, unsafe_allow_html=True)

    progress_placeholder = st.empty()
    
    cwd = Path.cwd()
    all_pdfs = list(cwd.rglob("*.pdf"))
    pdf_map = {p.name.lower(): p for p in all_pdfs}

    vectordb = Chroma(client=client, collection_name=collection_name, embedding_function=embeddings)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    
    try:
        for idx, target in enumerate(TARGET_FILENAMES):
            p = pdf_map.get(target.lower())
            if not p: continue
            
            # Format filename to beautiful title
            meta_info = parse_filename_metadata(target)
            stage_val = meta_info.get("stage", "?")
            
            subj_val = "Book"
            if meta_info.get("subject") == "sci": subj_val = "Science"
            elif meta_info.get("subject") == "math": subj_val = "Mathematics"
            elif meta_info.get("subject") == "eng": subj_val = "English"
            
            book_val = "Workbook" if meta_info.get("book") == "WB" else "Student Book"
            
            part_m = re.search(r"_([12])_", target)
            part_str = f" Part {part_m.group(1)}" if part_m else ""
            ans_str = " Answers" if meta_info.get("is_answers") else ""
            
            clean_title = f"Cambridge Stage {stage_val} {subj_val} {book_val}{part_str}{ans_str}"

            progress_placeholder.markdown(f"""
            <div class="thinking-container" style="margin: 20px auto; max-width: 600px;">
                <span class="thinking-text">⚡ High-Speed Caching Book {idx+1}/{len(TARGET_FILENAMES)}: {clean_title}</span>
                <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
            </div>
            """, unsafe_allow_html=True)

            try:
                loader = PyPDFLoader(str(p))
                docs = loader.load()
                meta = parse_filename_metadata(p.name)
                for d in docs:
                    d.metadata = {**d.metadata, **meta}
                    
                split_docs = splitter.split_documents(docs)
                
                # INCREASED BATCH SIZE: Sending 3x more data per request!
                batch_size = 150 
                for i in range(0, len(split_docs), batch_size):
                    batch = split_docs[i:i + batch_size]
                    
                    # ADAPTIVE RATE LIMITING: Run at max speed, only sleep if Google throttles us
                    max_retries = 5
                    for attempt in range(max_retries):
                        try:
                            vectordb.add_documents(batch)
                            # SUCCESS! Do NOT sleep. Move to next batch instantly.
                            break 
                        except Exception as e:
                            error_str = str(e).lower()
                            if attempt < max_retries - 1:
                                # Only back off if we hit a Rate Limit (429) or Quota error
                                if "429" in error_str or "quota" in error_str or "exhausted" in error_str:
                                    wait_time = 5 * (attempt + 1)
                                    time.sleep(wait_time) 
                                else:
                                    time.sleep(2)
                            else:
                                print(f"Skipping batch in {target} due to API Error: {e}")

                del loader
                del docs
                del split_docs
                gc.collect()

            except Exception as e:
                print(f"Error on {target}: {e}")
                continue

    finally:
        # Guarantee UI cleanup
        progress_placeholder.empty()
        status_placeholder.markdown("""
            <div class="status-indicator status-ready" title="Books Ready!">
                <span class="book-icon">📗</span>
            </div>
        """, unsafe_allow_html=True)

    return vectordb

# Initialize Vector DB
if "vectordb" not in st.session_state:
    st.session_state.vectordb = get_vector_db()

vectordb = st.session_state.vectordb

if vectordb:
    st.markdown("""
        <div class="status-indicator status-ready" title="Books Ready!">
            <span class="book-icon">📗</span>
        </div>
    """, unsafe_allow_html=True)

# --- 8. ANIMATION FUNCTIONS (FIXED POSITION) ---
def show_thinking_animation_rotating(placeholder):
    messages = [
        "🔍 Helix is searching the textbooks 📚",
        "🧠 Helix is analyzing your question 💭",
        "✨ Helix is forming your answer 📝",
        "🔬 Helix is processing information 🧪"
    ]
    thinking_html = f"""
    <div style="display: flex; align-items: center; gap: 8px; padding-top: 10px;">
        <span style="color: #fc8404; font-size: 15px; font-weight: 600;">{random.choice(messages)}</span>
        <div class="thinking-dots" style="margin-top: 5px;">
            <div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div>
        </div>
    </div>
    """
    placeholder.markdown(thinking_html, unsafe_allow_html=True)

def show_thinking_animation(message="Helix is thinking"):
    return st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 8px; padding-top: 10px;">
        <span style="color: #fc8404; font-size: 15px; font-weight: 600;">{message}</span>
        <div class="thinking-dots" style="margin-top: 5px;">
            <div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- 10. INITIALIZE NATIVE SESSION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content":
            "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\n"
            "I can answer your doubts, draw diagrams, and create quizes! 📚\n\n"
            "**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n"
            "*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\n"
            "What are we learning today?"
        }
    ]

# --- 11. DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- 12. MEMORY: LAST 8 MESSAGES ---
def get_last_n_messages_for_model(messages, n=8):
    msgs = [m for m in messages if not m.get("is_image")]
    history = []
    for m in msgs[-n:]:
        role = "user" if m["role"] == "user" else "model"
        history.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return history

# --- 13. RAG RETRIEVAL WITH MEMORY FILTERS ---
def retrieve_rag_context(query: str, chat_history: list, k: int = 8):
    if not vectordb: return "", []

    # CONVERSATION MEMORY: Look at the last 3 user messages to infer the subject/grade
    recent_user_msgs = [m["content"] for m in chat_history if m["role"] == "user"]
    history_text = " ".join(recent_user_msgs[-3:]) + " " + query
    
    subj = infer_subject(history_text)
    stage = infer_stage(history_text)

    if subj == "eng" and stage == 9: return "", []

    search_filter = {}
    if subj: search_filter["subject"] = subj
    if stage: search_filter["stage"] = stage

    final_docs = []
    
    if search_filter:
        try:
            if len(search_filter) > 1:
                filter_dict = {"$and": [{k: v} for k, v in search_filter.items()]}
            else:
                filter_dict = search_filter
            final_docs = vectordb.similarity_search(query, k=k, filter=filter_dict)
        except Exception:
            final_docs = []
    else:
        final_docs = vectordb.similarity_search(query, k=k)

    lines = []
    for i, d in enumerate(final_docs, 1):
        src = d.metadata.get("filename") or d.metadata.get("source", "Unknown")
        page = d.metadata.get("page", "Unknown")
        lines.append(f"Source {i}\nFile: {src}\nPage: {page}\nContent:\n{d.page_content}")

    return "\n\n".join(lines), final_docs

# --- 14. MAIN LOOP ---
if prompt := st.chat_input("Ask Helix a question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()
        show_thinking_animation_rotating(thinking_placeholder)

        try:
            # Pass the session state messages to RAG so it Remembers the subject!
            rag_context, _docs = retrieve_rag_context(prompt, st.session_state.messages, k=8)
            chat_history_contents = get_last_n_messages_for_model(st.session_state.messages[:-1], n=8)

            augmented_prompt = f"""
You are Helix. You have access to the following textbook context (hidden from the user).

INSTRUCTIONS:
1. If the hidden context contains the answer, use it.
2. If the hidden context is empty or irrelevant, seamlessly use your own knowledge.
3. STRICT RULE: NEVER mention the words "context", "excerpt", "textbook", "materials", or filenames. Act as if you know everything natively. Make the conversation feel 100% natural.

HIDDEN CONTEXT:
{rag_context}

USER QUESTION:
{prompt}
""".strip()

            current_content = types.Content(role="user", parts=[types.Part.from_text(text=augmented_prompt)])

            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=chat_history_contents + [current_content],
                config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION)
            )

            bot_text = text_response.text
            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            if "IMAGE_GEN:" in bot_text:
                try:
                    img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    img_thinking = st.empty()
                    with img_thinking: show_thinking_animation("🖌️ Painting diagram...")
                    img_resp = client.models.generate_content(
                        model="gemini-3-pro-image-preview",
                        contents=[img_desc],
                        config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE'])
                    )
                    for part in img_resp.parts:
                        if part.inline_data:
                            st.image(part.inline_data.data, caption="Generated by Helix")
                            st.session_state.messages.append({"role": "assistant", "content": part.inline_data.data, "is_image": True})
                            img_thinking.empty()
                except Exception:
                    st.error("Image generation failed.")

        except Exception as e:
            thinking_placeholder.empty()
            st.error(f"Helix Error: {e}")
