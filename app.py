import streamlit as st
import os
import time
import chromadb
from pypdf import PdfReader
from pathlib import Path
from google import genai
from google.genai import types

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
<div class="subtitle">Your AI Education Platform</div>
""", unsafe_allow_html=True)

# --- 3. HELPER: FORMAT FILE NAMES ---
def get_friendly_name(filename):
    if not filename: return "Textbook"
    name = filename.replace(".pdf", "").replace(".PDF", "")
    parts = name.split("_")
    if len(parts) < 3 or parts[0] != "CIE": return filename
    grade, book_type = parts[1], "Workbook" if "WB" in parts else "Textbook"
    subject = "Science" if "Sci" in parts else "Math" if "Math" in parts else "English" if "Eng" in parts else "Subject"
    return f"Cambridge {subject} {book_type} {grade}"

# --- 4. SYSTEM INSTRUCTIONS ---
SYSTEM_INSTRUCTION = """
You are Helix, an advanced AI Educational Tutor.

### RULE 1: THE TWO-STEP SEARCH (CRITICAL)
- STEP 1: You MUST answer using the "Extracted Textbook Context" provided in the prompt. If you find the answer there, cite the book name provided in the context (e.g., "Source: Cambridge Science Textbook 7").
- STEP 2: If the context does not contain the answer, you must state: "I couldn't find this in the textbook library, but here is what I know:" and use your general knowledge.

### RULE 2: ASSESSMENTS
- If asked for a quiz, generate Checkpoint-style formats (Paper 1 & 2), 50 marks. Put the citation ONLY ONCE at the very bottom.

### RULE 3: IMAGE GENERATION
- IF the user asks for a diagram, output ONLY this exact command:
  IMAGE_GEN: [A high-quality illustration of the topic, detailed, white background, with labels]
"""

# --- 5. THE NEW "REAL RAG" ENGINE ---
@st.cache_resource(show_spinner=False)
def initialize_vector_db():
    msg_placeholder = st.empty()
    
    # Initialize Local ChromaDB
    db_path = os.path.join(os.getcwd(), "helix_vector_db")
    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_or_create_collection(name="textbooks")

    # If DB already has data, load instantly!
    if collection.count() > 0:
        msg_placeholder.success(f"⚡ Connected to Vector Database! ({collection.count()} knowledge chunks loaded)")
        time.sleep(2)
        msg_placeholder.empty()
        return collection

    # If DB is empty, process the PDFs
    with msg_placeholder.chat_message("assistant"):
        st.markdown(f"""
        <div class="thinking-container">
            <span class="thinking-text">⚙️ Initializing Vector Database for the first time. This may take a few minutes...</span>
            <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
        </div>
        """, unsafe_allow_html=True)

    pdf_files = list(Path.cwd().rglob("*.pdf"))
    
    for pdf_path in pdf_files:
        friendly_name = get_friendly_name(pdf_path.name)
        try:
            reader = PdfReader(pdf_path)
            full_text = ""
            for page in reader.pages:
                text = page.extract_text()
                if text: full_text += text + "\n"
            
            # CHUNKING: Split text into 1000-character blocks
            chunk_size = 1000
            chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
            
            # Add to ChromaDB (Chroma handles the embedding math locally automatically using its default fast model)
            for i, chunk in enumerate(chunks):
                collection.add(
                    documents=[chunk],
                    metadatas=[{"source": friendly_name}],
                    ids=[f"{pdf_path.name}_chunk_{i}"]
                )
        except Exception as e:
            print(f"Skipped {pdf_path.name}: {e}")

    msg_placeholder.empty()
    return collection

# --- 6. HISTORY FORMATTING ---
def get_recent_history_contents(messages, max_messages=6):
    history_contents = []
    text_msgs = [m for m in messages if not m.get("is_image") and not m.get("is_greeting")]
    for msg in text_msgs[-max_messages:]:
        role = "user" if msg["role"] == "user" else "model"
        history_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
    return history_contents

# --- 7. INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly AI tutor powered by Vector Retrieval! 📖\n\nI can search thousands of textbook pages instantly. What are we learning today?",
            "is_greeting": True
        }
    ]

if "vector_db" not in st.session_state:
    st.session_state.vector_db = initialize_vector_db()

# --- 8. DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- 9. MAIN LOOP ---
if prompt := st.chat_input("Ask Helix a question..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        thinking_placeholder = st.empty()
        thinking_placeholder.markdown(f"""
            <div class="thinking-container">
                <span class="thinking-text">🧠 Searching Vector Database...</span>
                <div class="thinking-dots"><div class="thinking-dot"></div><div class="thinking-dot"></div><div class="thinking-dot"></div></div>
            </div>
        """, unsafe_allow_html=True)
        
        try:
            # 1. VECTOR SEARCH: Query ChromaDB for the 30 most relevant textbook chunks
            results = st.session_state.vector_db.query(
                query_texts=[prompt],
                n_results=30
            )
            
            # 2. Extract the text and metadata (sources)
            retrieved_chunks = results['documents'][0]
            retrieved_sources = results['metadatas'][0]
            
            context_string = ""
            unique_sources = set()
            
            for chunk, meta in zip(retrieved_chunks, retrieved_sources):
                source_name = meta["source"]
                unique_sources.add(source_name)
                # Separating chunks clearly so Gemini understands the transitions
                context_string += f"--- Source: {source_name} ---\n{chunk}\n\n"

            # Update UI to show what it found instantly
            if unique_sources:
                st.caption(f"⚡ *Deep Scan Found Data In: {', '.join(unique_sources)}*")
            else:
                st.caption("⚡ *No precise vector match found. Using general knowledge.*")

            
            chat_history_contents = get_recent_history_contents(st.session_state.messages[:-1], max_messages=6)
            
            # 3. Inject the retrieved vector context into Gemini's prompt
            enhanced_prompt = f"Extracted Textbook Context:\n{context_string}\n\nUser Query: {prompt}\n\nPlease answer the query using ONLY the context above. If it's not in the context, use your general knowledge."
            
            current_content = types.Content(role="user", parts=[types.Part.from_text(text=enhanced_prompt)])
            full_contents = chat_history_contents + [current_content]

            # 4. Generate Answer (Lightning Fast now!)
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
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # Image Gen logic
            if "IMAGE_GEN:" in bot_text:
                try:
                    img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\n")[0]
                    img_thinking = st.empty()
                    img_thinking.markdown("*🖌️ Painting diagram...*")
                    
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

