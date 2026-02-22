# --- MUST BE THE ABSOLUTE FIRST LINES IN THE FILE ---
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import streamlit as st
import os
import time
import re
import shutil
import random
from pathlib import Path
import gc

from google import genai
from google.genai import types

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import chromadb

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- EMERGENCY DATABASE RESET BUTTON ---
with st.sidebar:
    st.warning("⚠️ Admin Tools")
    if st.button("Reset Database (Fix 'I can't find this' error)"):
        persist_dir = "/tmp/helix_chroma_db"
        if os.path.exists(persist_dir):
            shutil.rmtree(persist_dir)  
            st.success("Database deleted! Please refresh the web page.")
        else:
            st.info("Database doesn't exist yet.")

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
ALSO: In MCQs, randomize the answers, because in a previous test I did using you, the answers were 1)C, 2)C, 3)C, 4)C. REMEMBER, RANDOMIZE MCQ ANSWERS
ALSO: Use BOTH WB (Workbook) AND TB (Textbook) because the WB has questions mainly, but SB has theory. Using BOTH WILL GIVE YOU A WIDE RANGE OF QUESTIONS.
ALSO: DO NOT INTRODUCE YOURSELF LIKE "I am Helix!" as I have already created and introduction message. Just get to the user's query immediately.

### RULE 1: SOURCE PRIORITY
- First, ALWAYS check the content of the retrieved RAG PDF chunks to answer a question.
- If the answer is NOT in the retrieved textbook chunks, you must state: "I couldn't find this in your textbook, but here is what I know:" and then answer using your general knowledge.
- The subject is seen in the last part, like this: _Eng.pdf, _Math.pdf, _Sci.pdf

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
  - Science (Checkpoint style): produce Paper 1 and/or Paper 2 (default both) as a 50‑mark, ~45‑minute structured written paper with numbered questions showing marks like "(3)", mixing knowledge/application plus data handling (tables/graphs) and at least one investigation/practical-skills question (variables, fair test, reliability, improvements) and at least one diagram task; then include a point-based mark scheme with working/units for calculations.
  - Mathematics (Checkpoint style): produce Paper 1 non‑calculator and Paper 2 calculator (default both), each ~45 minutes and 50 marks, mostly structured questions with marks shown, covering arithmetic/fractions/percent, algebra, geometry, and data/statistics, including at least one multi-step word problem and requiring "show working"; then give an answer key with method marks for 2+ mark items.
  - English (Checkpoint style): produce Paper 1 Non‑fiction and Paper 2 Fiction (default both), each ~45 minutes and 50 marks, using original passages you write (no copyrighted extracts), with structured comprehension (literal + inference + writer's effect) and one longer directed/creative writing task per paper; then include a mark scheme (acceptable reading points per mark) plus a simple writing rubric (content/organisation/style & accuracy) and a brief high-scoring outline.

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

# --- 7. RAG: BIG DATA / LOW MEMORY ENGINE ---
def get_vector_db():
    persist_dir = "/tmp/helix_chroma_db"
    
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=api_key
    )

    client = chromadb.PersistentClient(path=persist_dir)
    collection_name = "helix_collection"

    # 1. Check if DB is already fully built
    try:
        col = client.get_collection(collection_name)
        if col.count() > 0:
            return Chroma(client=client, collection_name=collection_name, embedding_function=embeddings)
    except Exception:
        pass

    # 2. Setup UI
    status_placeholder = st.empty()
    status_placeholder.markdown("""
        <div class="status-indicator status-loading">
            <span class="book-icon">📕</span>
            <div class="spinner"></div>
        </div>
        """, unsafe_allow_html=True)

    msg_placeholder = st.empty()
    progress_text = st.empty()
    with msg_placeholder.chat_message("assistant"):
        progress_text.markdown("""
        <div class="thinking-container">
            <span class="thinking-text">🔄 Helix is building the database... (Large files detected)</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

    cwd = Path.cwd()
    all_pdfs = list(cwd.rglob("*.pdf"))
    pdf_map = {p.name.lower(): p for p in all_pdfs}

    vectordb = Chroma(client=client, collection_name=collection_name, embedding_function=embeddings)
    
    # 3. LOW MEMORY LOOP: Process ONE book at a time
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    
    for idx, target in enumerate(TARGET_FILENAMES):
        p = pdf_map.get(target.lower())
        if not p: continue
        
        progress_text.markdown(f"""
        <div class="thinking-container">
            <span class="thinking-text">🔄 Processing Book {idx+1}/{len(TARGET_FILENAMES)}: {target}</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

        try:
            # Load ONE document
            loader = PyPDFLoader(str(p))
            docs = loader.load()
            meta = parse_filename_metadata(p.name)
            for d in docs:
                d.metadata = {**d.metadata, **meta}
                
            # Split ONE document
            split_docs = splitter.split_documents(docs)
            
            # Send to Google in tiny batches (to avoid rate limits and memory spikes)
            batch_size = 50
            for i in range(0, len(split_docs), batch_size):
                batch = split_docs[i:i + batch_size]
                vectordb.add_documents(batch)
                time.sleep(1) # Crucial: Let Google breathe so it doesn't Time Out

            # LOW MEMORY TRICK: Force Python to delete the 250MB PDF from RAM before the next loop
            del loader
            del docs
            del split_docs
            gc.collect()

        except Exception as e:
            st.error(f"Error on {target}: {e}")
            continue

    # Clean UI
    msg_placeholder.empty()
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

# --- 8. ANIMATION FUNCTIONS (INSTANT) ---
def show_thinking_animation_rotating(placeholder):
    messages = [
        "🔍 Helix is searching the textbooks 📚",
        "🧠 Helix is analyzing your question 💭",
        "✨ Helix is forming your answer 📝",
        "🔬 Helix is processing information 🧪"
    ]
    thinking_html = f"""
    <div class="thinking-container">
        <span class="thinking-text">{random.choice(messages)}</span>
        <div class="thinking-dots">
            <div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div>
        </div>
    </div>
    """
    placeholder.markdown(thinking_html, unsafe_allow_html=True)

def show_thinking_animation(message="Helix is thinking"):
    return st.markdown(f"""
    <div class="thinking-container">
        <span class="thinking-text">{message}</span>
        <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
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

# --- 13. RAG RETRIEVAL (TEST MODE - NO FILTERS AT ALL) ---
def retrieve_rag_context(query: str, k: int = 8):
    if not vectordb: return "", []

    # TEST MODE: We completely bypass subject/stage filters here
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
            rag_context, _docs = retrieve_rag_context(prompt, k=8)
            chat_history_contents = get_last_n_messages_for_model(st.session_state.messages[:-1], n=8)

            with st.expander("🔍 See what textbook pages Helix read for this question"):
                if rag_context.strip(): st.text(rag_context)
                else: st.warning("No context retrieved. Database might be empty or missing.")

            augmented_prompt = f"""
You are Helix, a helpful tutor. You are answering a student based on textbook excerpts.

INSTRUCTIONS:
1. Carefully read the RAG Context below to find the answer.
2. Use the "File" and "Page" from the context to cite your source and avoid mixing up subjects.
3. If the context contains enough information to answer the prompt (even partially), use it!
4. IF the RAG Context is completely irrelevant or missing the answer, you MUST state: "I couldn't find this in your textbook, but here is what I know:" and then answer fully using your general knowledge.

RAG Context:
{rag_context}

Question:
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

