st.markdown("""
<style>
/* Use Streamlit theme variables so Light + Dark both stay readable */
.stApp{
  background: radial-gradient(800px circle at 50% 0%,
              rgba(0, 212, 255, 0.08),
              rgba(0, 212, 255, 0.00) 60%),
              var(--background-color);
  color: var(--text-color);
}

/* Your header styles */
.big-title {
  font-family: 'Inter', sans-serif;
  color: #00d4ff;
  text-align: center;
  font-size: 48px;
  font-weight: 1200;
  letter-spacing: -3px;
  margin-bottom: 0px;
}
.subtitle {
  text-align: center;
  color: var(--text-color);
  opacity: 0.55;
  font-size: 18px;
  margin-bottom: 30px;
}

/* Thinking animation uses theme secondary bg */
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

<div class="big-title">🧬 epi.ai</div>
<div class="subtitle">Your friendly science tutor, Epi</div>
""", unsafe_allow_html=True)
