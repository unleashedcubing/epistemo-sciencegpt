import streamlit as st
import os
import time
import io
from google import genai
from google.genai import types

# --- PAGE CONFIG ---
st.set_page_config(page_title="helix.ai", page_icon="📚", layout="centered")

# --- THEME CSS ---
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

/* Glowing title */
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 48px;
  font-weight: 1200;
  letter-spacing: -3px;
  margin-bottom: 0px;
  text-shadow:
    0 0 6px rgba(0, 212, 255, 0.55),
    0 0 18px rgba(0, 212, 255, 0.35),
    0 0 42px rgba(0, 212, 255, 0.20);
  animation: helix-glow 2.2s ease-in-out infinite;
}

@keyframes helix-glow {
  0%, 100% {
    text-shadow:
      0 0 6px rgba(0, 212, 255, 0.45),
      0 0 18px rgba(0, 212, 255, 0.28),
      0 0 42px rgba(0, 212, 255, 0.16);
  }
  50% {
    text-shadow:
      0 0 8px rgba(0, 212, 255, 0.75),
      0 0 24px rgba(0, 212, 255, 0.45),
      0 0 54px rgba(0, 212, 255, 0.24);
  }
}

.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.60;
  font-size: 18px;
  margin-bottom: 30px;
}

/* Thinking Animation */
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

<div class="big-title">🧬 helix.ai</div>
<div class="subtitle">Your CIE Tutor for Grade 6-8!</div>
""", unsafe_allow_html=True)


# --- API SETUP ---
if "GOOGLE_API_KEY" in st.secrets:
    api_key = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: GOOGLE_API_KEY not found in Streamlit Secrets.")
    st.stop()

client = genai.Client(api_key=api_key)

# --- SYSTEM INSTRUCTIONS ---
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
  - Science (Checkpoint style): produce Paper 1 and/or Paper 2 (default both) as a 50‑mark, ~45‑minute structured written paper with numbered questions showing marks like “(3)”, mixing knowledge/application plus data handling (tables/graphs) and at least one investigation/practical-skills question (variables, fair test, reliability, improvements) and at least one diagram task; then include a point-based mark scheme with working/units for calculations.
  - Mathematics (Checkpoint style): produce Paper 1 non‑calculator and Paper 2 calculator (default both), each ~45 minutes and 50 marks, mostly structured questions with marks shown, covering arithmetic/fractions/percent, algebra, geometry, and data/statistics, including at least one multi-step word problem and requiring “show working”; then give an answer key with method marks for 2+ mark items.
  - English (Checkpoint style): produce Paper 1 Non‑fiction and Paper 2 Fiction (default both), each ~45 minutes and 50 marks, using original passages you write (no copyrighted extracts), with structured comprehension (literal + inference + writer’s effect) and one longer directed/creative writing task per paper; then include a mark scheme (acceptable reading points per mark) plus a simple writing rubric (content/organisation/style & accuracy) and a brief high-scoring outline.

### RULE 5: ARMAAN STYLE
If a user asks you to reply in Armaan Style, you have to explain in expert physicist/chemist/biologist/mathematician/writer terms, with difficult out of textbook sources. You can then simple it down if the user wishes.
"""


# --- TEXTBOOK UPLOADER (No Cache, Direct Upload) ---
def upload_textbooks():
    pdf_filenames = ["CIE_9_WB_Sci.pdf", "CIE_9_SB_Math.pdf", "CIE_9_SB_2_Sci.pdf", "CIE_9_SB_1_Sci.pdf",
                    "CIE_8_WB_Sci.pdf", "CIE_8_WB_ANSWERS_Math.pdf", "CIE_8_SB_Math.pdf", "CIE_8_SB_2_Sci.pdf",
                    "CIE_8_SB_2_Eng.pdf", "CIE_8_SB_1_Sci.pdf", "CIE_8_SB_1_Eng.pdf",
                    "CIE_7_WB_Sci.pdf", "CIE_7_WB_Math.pdf", "CIE_7_WB_Eng.pdf", "CIE_7_WB_ANSWERS_Math.pdf",
                    "CIE_7_SB_Math.pdf", "CIE_7_SB_2_Sci.pdf", "CIE_7_SB_2_Eng.pdf", "CIE_7_SB_1_Sci.pdf", "CIE_7_SB_1_Eng.pdf"] 
    active_files = []
    for fn in pdf_filenames:
        if os.path.exists(fn):
            try:
                # Fresh upload for the session to ensure active permission handles
                uploaded_file = client.files.upload(file=fn)
                active_files.append(uploaded_file)
                
                # Wait for ACTIVE state (crucial for Gemini to read them)
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(1)
                    uploaded_file = client.files.get(name=uploaded_file.name)
                    
            except Exception as e:
                st.sidebar.error(f"Error loading {fn}: {e}")
    return active_files

# --- THINKING ANIMATION ---
def show_thinking_animation(message="Helix is thinking"):
    thinking_html = f"""
    <div class="thinking-container">
        <span class="thinking-text">{message}</span>
        <div class="thinking-dots">
            <div class="thinking-dot"></div>
            <div class="thinking-dot"></div>
            <div class="thinking-dot"></div>
        </div>
    </div>
    """
    return st.markdown(thinking_html, unsafe_allow_html=True)

# --- INITIALIZE SESSION ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "👋 **Hey there! I'm Helix!**\n\nI'm your friendly CIE tutor here to help you ace your CIE exams! 📖\n\nI can answer your doubts, draw diagrams, and create quizes! 📚\n\n**Quick Reminder:** In the Cambridge system, your **Stage** is usually your **Grade + 1**.\n*(Example: If you are in Grade 7, you are studying Stage 8 content!)*\n\nWhat are we learning today?"}
    ]

if "textbook_handles" not in st.session_state:
    with st.spinner("Helix is reading the Cambridge Workbooks..."):
        st.session_state.textbook_handles = upload_textbooks()

# --- DISPLAY CHAT ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("is_image"):
            st.image(message["content"])
        else:
            st.markdown(message["content"])

# --- MAIN CHAT LOOP ---
if prompt := st.chat_input("Ask Helix a question from your books, create diagrams, quizes and more..."):
    # 1. Show User Message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        # Show thinking animation
        thinking_placeholder = st.empty()
        with thinking_placeholder:
            show_thinking_animation("🔍 Helix is searching the textbooks 📚")
        
        try:
            # 2. TEXT RESPONSE (Gemini 2.5 Flash - Direct File Access)
            # We send the file handles + prompt directly. 2.5 Flash handles this.
            text_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=st.session_state.textbook_handles + [prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=[{"google_search": {}}]
                )
            )
            
            bot_text = text_response.text
            
            # Clear thinking animation and show response
            thinking_placeholder.empty()
            st.markdown(bot_text)
            st.session_state.messages.append({"role": "assistant", "content": bot_text})

            # 3. IMAGE GENERATION (Gemini 3 Pro Multimodal)
            if "IMAGE_GEN:" in bot_text:
                img_desc = bot_text.split("IMAGE_GEN:")[1].strip().split("\\n")[0]
                
                img_thinking_placeholder = st.empty()
                with img_thinking_placeholder:
                    show_thinking_animation("🖌️ Helix is painting a diagram 🎨")
                
                for attempt in range(2):
                    try:
                        image_response = client.models.generate_content(
                            model="gemini-3-pro-image-preview",
                            contents=[img_desc],
                            config=types.GenerateContentConfig(
                                response_modalities=['TEXT', 'IMAGE']
                            )
                        )
                        
                        for part in image_response.parts:
                            if part.inline_data:
                                img_bytes = part.inline_data.data
                                img_thinking_placeholder.empty()
                                st.image(img_bytes, caption="Generated by Helix")
                                st.session_state.messages.append({
                                    "role": "assistant", 
                                    "content": img_bytes, 
                                    "is_image": True
                                })
                        break
                    except Exception as inner_e:
                        if "503" in str(inner_e) and attempt == 0:
                            time.sleep(2)
                            continue
                        else:
                            img_thinking_placeholder.empty()
                            st.error(f"Image generation failed: {inner_e}")

        except Exception as e:
            thinking_placeholder.empty()
            if "403" in str(e) or "PERMISSION_DENIED" in str(e):
                st.error("Helix's connection to the workbooks timed out. Please refresh the page!")
                del st.session_state.textbook_handles
            else:
                st.error(f"Helix encountered a technical glitch: {e}")
