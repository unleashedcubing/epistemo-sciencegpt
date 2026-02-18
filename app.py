import streamlit as st
import os
import time
from pathlib import Path
from google import genai
from google.genai import types

# --- 1. SETUP & CONFIGURATION ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- 2. API CLIENT SETUP ---
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("🚨 Critical Error: GOOGLE_API_KEY not found. Please set it in Secrets or Environment Variables.")
        st.stop()

try:
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error(f"🚨 Failed to initialize Gemini Client: {e}")
    st.stop()

# --- 3. THEME CSS ---
st.markdown("""
<style>
/* Theme-aware app background */
.stApp {
  background:
    radial-gradient(800px circle at 50% 0%,
      rgba(0, 212, 255, 0.08),
      rgba(0, 212, 255, 0.00) 60%),
    var(--background-color);
  color: var(--text-color);
}
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 48px;
  font-weight: 1200;
  letter-spacing: -3px;
  margin-bottom: 0px;
  text-shadow: 0 0 6px rgba(0, 212, 255, 0.55);
  animation: helix-glow 2.2s ease-in-out infinite;
}
@keyframes helix-glow {
  0%, 100% { text-shadow: 0 0 6px rgba(0, 212, 255, 0.45); }
  50% { text-shadow: 0 0 8px rgba(0, 212, 255, 0.75); }
}
.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.60;
  font-size: 18px;
  margin-bottom: 30px;
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
.thinking-text { color: #fc8404; font-size: 14px; font-weight: 600; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background-color: #fc8404;
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
- First, ALWAYS check the content of the uploaded PDF files to answer a question.
- If the answer is NOT in the textbook, you must state: "I couldn't find this in your textbook, but here is what I found online:" and then answer using your general knowledge.
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

# --- 5. ROBUST FILE UPLOADER & CACHING ---
def upload_textbooks():
    """
    Finds and uploads textbooks with robust error handling for empty/corrupt files.
    """
    target_filenames = [
        "CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
        "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
        "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
        "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
        "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"
    ]
    
    active_files = []
    
    # 🔍 DEBUG: Show what files actually exist in the environment
    st.sidebar.markdown("### 📂 File System Debug")
    cwd = Path.cwd()
    st.sidebar.code(f"Current Dir: {cwd}")
    
    # Find all PDFs recursively
    try:
        all_pdfs = list(cwd.rglob("*.pdf"))
        st.sidebar.write(f"📄 Total PDFs found: {len(all_pdfs)}")
        
        if len(all_pdfs) == 0:
            st.sidebar.error("❌ ZERO PDFs found. Did you commit them to Git?")
            return []
    except Exception as e:
        st.sidebar.error(f"Error scanning directory: {e}")
        return []

    # Map filename (lowercase) to full path for easy lookup
    pdf_map = {p.name.lower(): p for p in all_pdfs}

    # Progress bar
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    for i, target_name in enumerate(target_filenames):
        progress = (i + 1) / len(target_filenames)
        progress_bar.progress(progress)
        
        # Robust lookup
        found_path = pdf_map.get(target_name.lower())
        
        if found_path:
            try:
                # 1. Check File Size
                file_size_bytes = found_path.stat().st_size
                file_size_mb = file_size_bytes / (1024 * 1024)
                
                if file_size_bytes == 0:
                    st.sidebar.error(f"❌ Skipped {target_name}: File is empty (0 bytes)!")
                    continue
                
                status_text.text(f"⬆️ Uploading: {target_name} ({file_size_mb:.1f} MB)...")
                
                # 2. UPLOAD with Retry
                uploaded_file = None
                upload_success = False
                
                for attempt in range(2): # Try twice
                    try:
                        uploaded_file = client.files.upload(
                            file=found_path,
                            config={'mime_type': 'application/pdf'}
                        )
                        upload_success = True
                        break # Success!
                    except Exception as upload_err:
                        if attempt == 0:
                            time.sleep(2) # Wait and retry
                        else:
                            st.sidebar.warning(f"⚠️ Upload failed f
