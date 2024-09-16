# This is an adjusted version of the:
# https://github.com/tcsenpai/ol1
#
# Which is a fork of the original:
# https://github.com/bklieger-groq/g1

import streamlit as st
import json
import time
import requests  # Add this import for making HTTP requests to Ollama
from dotenv import load_dotenv
import os

load_dotenv()

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')
OLLAMA_OPTIONS = os.getenv('OLLAMA_OPTIONS', 'num_predict=300,temperature=0.2')


def parse_options(options):
    parsed_options = {}
    for opt in options.split(','):
        k, v = opt.split('=')
        if k.strip() != "stop":
            parsed_options[k.strip()] = float(v.strip()) if '.' in v else int(v.strip())
        else:
            parsed_options[k.strip()] = v.strip()
    return parsed_options


def make_api_call(messages, max_tokens, is_final_answer=False):
    for attempt in range(3):
        try:
            response = requests.post(f"{OLLAMA_URL}/api/chat",
                                     json={
                                         "model": OLLAMA_MODEL,
                                         "messages": messages,
                                         "stream": False,
                                         "format": "json",
                                         "options": parse_options(OLLAMA_OPTIONS),
                                     })
            response.raise_for_status()
            data = json.loads(response.json()["message"]["content"])
            if "title" not in data or "content" not in data:
                raise ValueError("Response JSON is missing 'title' or 'content' fields.")
            return data

        except Exception as e:
            if attempt == 2:
                if is_final_answer:
                    return {
                        "title":
                        "Error",
                        "content":
                        f"Failed to generate final answer after 3 attempts. Error: {str(e)}"
                    }
                else:
                    return {
                        "title": "Error",
                        "content":
                        f"Failed to generate step after 3 attempts. Error: {str(e)}",
                        "next_action": "final_answer"
                    }
            time.sleep(1)  # Wait for 1 second before retrying


def generate_response(prompt):
    messages = [{
        "role":
        "system",
        "content":
        """You are an expert AI assistant that explains your reasoning step by step. For each step, provide a title that describes what you're doing in that step, along with the content. Decide if you need another step or if you're ready to give the final answer. Respond in JSON format with 'title', 'content', and 'next_action' (either 'continue' or 'final_answer') keys. USE AS MANY REASONING STEPS AS POSSIBLE. AT LEAST 3. BE AWARE OF YOUR LIMITATIONS AS AN LLM AND WHAT YOU CAN AND CANNOT DO. IN YOUR REASONING, INCLUDE EXPLORATION OF ALTERNATIVE ANSWERS. CONSIDER YOU MAY BE WRONG, AND IF YOU ARE WRONG IN YOUR REASONING, WHERE IT WOULD BE. FULLY TEST ALL OTHER POSSIBILITIES. YOU CAN BE WRONG. WHEN YOU SAY YOU ARE RE-EXAMINING, ACTUALLY RE-EXAMINE, AND USE ANOTHER APPROACH TO DO SO. DO NOT JUST SAY YOU ARE RE-EXAMINING. USE AT LEAST 3 METHODS TO DERIVE THE ANSWER. USE BEST PRACTICES.

Example of a valid JSON response:
```json
{
    "title": "Identifying Key Information",
    "content": "To begin solving this problem, we need to carefully examine the given information and identify the crucial elements that will guide our solution process. This involves...",
    "next_action": "continue"
}```
"""
    }, {
        "role": "user",
        "content": prompt
    }, {
        "role":
        "assistant",
        "content":
        "Thank you! I will now think step by step following my instructions, starting at the beginning after decomposing the problem."
    }]

    steps = []
    step_count = 1
    total_thinking_time = 0

    while True:
        start_time = time.time()
        step_data = make_api_call(messages, 300)
        end_time = time.time()
        thinking_time = end_time - start_time
        total_thinking_time += thinking_time

        steps.append(
            (f"Step {step_count}: {step_data.get('title', 'Untitled Step')}",
             step_data.get('content', json.dumps(step_data,
                                                 indent=2)), thinking_time))

        messages.append({
            "role": "assistant",
            "content": json.dumps(step_data)
        })

        if step_data.get('next_action', 'continue') == 'final_answer':
            break

        step_count += 1

        # Yield after each step for Streamlit to update
        yield steps, None  # We're not yielding the total time until the end

    # Generate final answer
    messages.append({
        "role":
        "user",
        "content":
        "Please provide the final answer based on your reasoning above."
    })

    start_time = time.time()
    final_data = make_api_call(messages, 200, is_final_answer=True)
    end_time = time.time()
    thinking_time = end_time - start_time
    total_thinking_time += thinking_time

    steps.append(("Final Answer", final_data['content'], thinking_time))

    yield steps, total_thinking_time


def main():
    st.set_page_config(page_title="ol1", page_icon="🧠", layout="wide")

    st.markdown(f"**Current Configuration:**")
    st.markdown(f"- Ollama URL: `{OLLAMA_URL}`")
    st.markdown(f"- Ollama Model: `{OLLAMA_MODEL}`")

    # Initialize session state
    if 'has_generated_response' not in st.session_state:
        st.session_state.has_generated_response = False

    # Text input for user query
    user_query = st.text_input(
        "Enter your query:",
        placeholder="e.g., How many 'R's are in the word strawberry?")

    if user_query and not st.session_state.has_generated_response:
        st.write("Generating response...")
        # Create empty elements to hold the generated text and total time
        response_container = st.empty()
        time_container = st.empty()

        # Generate and display the response
        for steps, total_thinking_time in generate_response(user_query):
            with response_container.container():
                for i, (title, content, thinking_time) in enumerate(steps):
                    if title.startswith("Final Answer"):
                        st.markdown(f"### {title}")
                        st.markdown(content.replace('\n', '<br>'),
                                    unsafe_allow_html=True)
                    else:
                        with st.expander(title, expanded=True):
                            st.markdown(content.replace('\n', '<br>'),
                                        unsafe_allow_html=True)
            # Only show total time when it's available at the end
            if total_thinking_time is not None:
                time_container.markdown(
                    f"**Total thinking time: {total_thinking_time:.2f} seconds**"
                )

        st.session_state.has_generated_response = True

    # Retry button
    if st.session_state.has_generated_response:
        if st.button("Retry"):
            st.session_state.has_generated_response = False
            st.session_state.user_query = ""
            st.rerun()


if __name__ == "__main__":
    main()
