import streamlit as st
import google.generativeai as genai
import redis
import json
import uuid
from datetime import datetime, timedelta

# --- Configuration ---

# Configure the Gemini API
try:
    # Use st.secrets for deployment, but fallback to os.environ for local dev
    api_key = st.secrets.get("API_KEY")
    genai.configure(api_key=api_key)
except (AttributeError, KeyError):
    st.error("Gemini API key not found. Please set it as a Streamlit secret.")
    st.stop()

# Configure Redis Connection
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
except redis.exceptions.ConnectionError as e:
    st.error(f"Could not connect to Redis: {e}")
    st.info("Please ensure a Redis server is running on localhost:6379")
    st.stop()

# --- Constants ---
CHAT_SESSIONS_KEY = "geminichat:chat_sessions"
CURRENT_SESSION_KEY = "geminichat:current_session"
GENERAL_PERSONA = ''' You are an advanced conversational AI, designed to understand the user’s intent deeply and respond with precision, warmth, and reliability. Offer clear, actionable, and context‑sensitive answers that make complex topics simple. If the user asks 'Who are you?', reply: 'I'm a bot built upon the Gemini API, here to help you with anything you need.'
Your responses should be concise, informative, and engaging, always aiming to enhance the user’s experience. Avoid unnecessary jargon and focus on delivering value in every interaction.

'''


#Model and Session Management

def get_gemini_model():
    return genai.GenerativeModel(model_name="gemini-2.5-pro", system_instruction=GENERAL_PERSONA)

def load_chat_session(session_id):
    messages = get_session_messages(session_id)
    history = [
        {"role": "user" if msg["role"] == "user" else "model", "parts": [msg["content"]]}
        for msg in messages
    ]
    if history and history[-1]['role'] == 'model':
        history.pop()
    model = get_gemini_model()
    return model.start_chat(history=history)

##NEW FUNCTION: GROUP CHATS BY DATE --- ##
def group_sessions_by_date(sessions):
    """Groups chat sessions by date categories: Today, Yesterday, Previous 7 Days, etc."""
    groups = {"Today": [], "Yesterday": [], "Previous 7 Days": [], "Previous 30 Days": [], "Older": []}
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    for session in sessions:
        session_time = datetime.strptime(session["created_at"], "%Y-%m-%d %H:%M")
        session_date = session_time.date()
        delta = today - session_date

        if session_date == today:
            groups["Today"].append(session)
        elif session_date == yesterday:
            groups["Yesterday"].append(session)
        elif delta.days <= 7:
            groups["Previous 7 Days"].append(session)
        elif delta.days <= 30:
            groups["Previous 30 Days"].append(session)
        else:
            groups["Older"].append(session)
    return groups

def create_new_session():
    session_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    session_data = {"id": session_id, "title": "New Chat", "messages": [], "created_at": timestamp}
    redis_client.hset(CHAT_SESSIONS_KEY, session_id, json.dumps(session_data))
    redis_client.set(CURRENT_SESSION_KEY, session_id)
    initial_message = {"role": "assistant", "content": "Hello! How can I help you today?"}
    add_message_to_session(session_id, initial_message)
    return session_id

def get_current_session_id():
    session_id = redis_client.get(CURRENT_SESSION_KEY)
    if not session_id:
        return create_new_session()
    return session_id

def get_session_messages(session_id):
    session_data = redis_client.hget(CHAT_SESSIONS_KEY, session_id)
    return json.loads(session_data)["messages"] if session_data else []

def add_message_to_session(session_id, message):
    session_data_str = redis_client.hget(CHAT_SESSIONS_KEY, session_id)
    if session_data_str:
        session = json.loads(session_data_str)
        session["messages"].append(message)
        # Update title only if it's the default "New Chat"
        if message["role"] == "user" and session["title"] == "New Chat":
            session["title"] = f"{message['content'][:35]}..."
        redis_client.hset(CHAT_SESSIONS_KEY, session_id, json.dumps(session))

def get_all_sessions():
    sessions_data = redis_client.hgetall(CHAT_SESSIONS_KEY)
    sessions = [json.loads(s) for s in sessions_data.values()]
    return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

def delete_session(session_id):
    redis_client.hdel(CHAT_SESSIONS_KEY, session_id)
    if redis_client.get(CURRENT_SESSION_KEY) == session_id:
        redis_client.delete(CURRENT_SESSION_KEY)

## --- NEW: CUSTOM CSS FOR CHATGPT LOOK --- ##
def load_custom_css():
    """Injects custom CSS to style the app like ChatGPT."""
    css = """
    <style>
        /* Set dark theme as default */
        body {
            color: #fff;
            background-color: #343541;
        }
        h1 {
            text-align: center;
        }
        /* Main chat container */
        .main .block-container {
            padding-top: 2rem;
        }
        /* Sidebar styling */
        .st-emotion-cache-16txtl3 {
            background-color: #202123;
        }
        /* Style for "New Chat" button */
        .st-emotion-cache-16txtl3 .stButton>button {
            width: 100%;
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 5px;
            color: #fff;
            background-color: transparent;
            text-align: left;
        }
        /* Style for history buttons */
        .st-emotion-cache-16txtl3 .stButton>button[kind="secondary"] {
            border: none;
            text-align: left;
            padding-left: 0.5rem;
            font-size: 0.9rem;
        }
        .st-emotion-cache-16txtl3 .stButton>button[kind="secondary"]:hover {
            background-color: #343541;
        }
        /* History group subheaders */
        .st-emotion-cache-16txtl3 .stsubheader {
            color: #8e8ea0;
            font-size: 0.8rem;
            text-transform: uppercase;
            padding-left: 0.5rem;
            margin-bottom: 0.5rem;
        }
        /* Hide the delete button default background */
        button[title="Delete this chat"] {
            background: transparent !important;
            border: none !important;
        }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# --- Streamlit App ---
def main():
    st.set_page_config(page_title="AI Chatbot", page_icon="🤖", layout="wide")
    
    # Apply the custom CSS
    load_custom_css()

    session_id = get_current_session_id()
    if "current_session_id" not in st.session_state or st.session_state.current_session_id != session_id:
        st.session_state.current_session_id = session_id
        st.session_state.chat_session = load_chat_session(session_id)

    # --- Sidebar for Chat History ---
    with st.sidebar:
        if st.button("➕ New Chat", use_container_width=True):
            session_id = create_new_session()
            st.session_state.current_session_id = session_id
            st.session_state.chat_session = load_chat_session(session_id)
            st.rerun()

        st.markdown("---")

        # Get and group sessions
        all_sessions = get_all_sessions()
        grouped_sessions = group_sessions_by_date(all_sessions)

        # Display grouped sessions
        for group_name, sessions in grouped_sessions.items():
            if sessions:
                st.subheader(group_name)
                for session in sessions:
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        if st.button(session["title"], key=f"session_{session['id']}", use_container_width=True, type="secondary"):
                            if session['id'] != st.session_state.current_session_id:
                                st.session_state.current_session_id = session['id']
                                redis_client.set(CURRENT_SESSION_KEY, session['id'])
                                st.session_state.chat_session = load_chat_session(session['id'])
                                st.rerun()
                    with col2:
                        if st.button("🗑️", key=f"del_{session['id']}", help="Delete this chat"):
                            delete_session(session['id'])
                            if session['id'] == st.session_state.current_session_id:
                                st.session_state.current_session_id = get_current_session_id()
                                st.session_state.chat_session = load_chat_session(st.session_state.current_session_id)
                            st.rerun()

    # --- Main Chat Area ---
    st.title("N Chatbot")
    
    # Display messages
    messages = get_session_messages(st.session_state.current_session_id)
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle user input
    if user_prompt := st.chat_input("Ask anything..."):
        add_message_to_session(st.session_state.current_session_id, {"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        try:
            with st.spinner("Thinking..."):
                response = st.session_state.chat_session.send_message(user_prompt)
                add_message_to_session(st.session_state.current_session_id, {"role": "assistant", "content": response.text})
                with st.chat_message("assistant"):
                    st.markdown(response.text)
        except Exception as e:
            st.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()