from pydantic import BaseModel, Field

import asyncio
import chat as ch
import log
import llm
import selection

# CSSV - Choice Selection for Systematic Validation
ID_PREFIX = 'cssv'
logger = log.setup_logger(ID_PREFIX)

continue_params = {
  "max_tokens": 4,
  "temperature": 0.3,
  "top_p": 0.9,
}

selection_prompt = """
Below is an unfinished conversation between the User and their assistant.
Choose how the conversation should continue.

You will reply with a JSON object in a format like this:
{{ "choice": 1, "confidence": 0.3 }}
"choice" is the index of the option you choose
"confidence" is a score of confident you are in your choice, from 0.0 to 1.0


Conversation:
{conversation}

Options:
{options}
""".strip()

system_prompts = {
    "overfit": """
You challenge common assumptions. For each problem:
- You never jump to conclusions
- Consider if you're jumping to familiar but wrong answers
- Look for cases where obvious answers fail
- Test multiple interpretations
- Question if you're forcing a known solution to fit
- Start fresh if you catch yourself following a memorized path
""",

    "tracker": """
You ensure complete solutions:
- You never jump to conclusions
- Track each requirement as a separate test case
- Mark requirements as pass/fail for each proposed solution
- Reject partial matches that don't satisfy all conditions
- Keep requirements visible while solving
- Double-check nothing was ignored or forgotten
""",

    "bias": """
You identify hidden biases:
- You never jump to conclusions
- List your initial assumptions explicitly
- Question why you jumped to those conclusions
- Look for alternative interpretations
- Check if you're pattern-matching to known examples
- Start over if you catch yourself making unnecessary assumptions
""",

    "edge": """
You actively seek edge cases:
- You never jump to conclusions
- Test boundary conditions systematically
- Consider empty/null/extreme inputs
- Look for assumption-breaking examples
- Validate corner case handling
- Verify graceful failure modes
""",

    "meta": """
You examine your own reasoning process:
- You never jump to conclusions
- Monitor your confidence levels
- Notice when you're rushing to conclusions
- Identify emotional attachments to certain solutions
- Flag when you're relying too heavily on past patterns
- Step back to evaluate your approach objectively
""",

    "steel": """
You steelman opposing views:
- You never jump to conclusions
- Construct strongest possible counter-arguments
- Identify merits in alternative approaches
- Challenge your preferred solution rigorously
- Consider hybrid approaches
- Maintain intellectual honesty
"""
}


class Choice(BaseModel):
  choice: int = Field(
    description = "The index of the chosen option",
    ge=1,
    le=len(system_prompts)
  )
  confidence: float = Field(
    description = "The confidence in the choice",
    ge=0.0,
    le=1.0,
  )

async def continue_generation(**kwargs):
    chat = kwargs['chat']
    llm = kwargs['llm']

    # Generate a meaningful chunk to analyze
    preview_chat = chat.clone()
    preview_response = await llm.chat_completion(
        chat=preview_chat,
        params={"max_tokens": 64, "temperature": 0.8},
        resolve=True
    )

    # Analyze this potential response through different lenses
    analysis_tasks = []
    for name, prompt in system_prompts.items():
        analysis_chat = chat.clone()
        analysis_chat.system(prompt)
        analysis_chat.user(f"Analyze this potential response: {preview_response}\n\nWhat critical issues or improvements do you identify?")
        task = llm.chat_completion(chat=analysis_chat, resolve=True)
        analysis_tasks.append(task)

    analyses = await asyncio.gather(*analysis_tasks)

    # Select the most critical/valuable analysis
    selection = await llm.chat_completion(
        prompt=selection_prompt,
        schema=Choice,
        conversation=chat,
        options=analyses,
        resolve=True
    )

    # Generate improved response incorporating the chosen criticism
    improvement_chat = chat.clone()
    improvement_chat.system(f"""
    Improve this response: {preview_response}

    Based on this critical feedback: {analyses[selection['choice'] - 1]}

    Generate only the next natural segment of improved response.
    """)

    improved_chunk = await llm.chat_completion(
        chat=improvement_chat,
        params={"max_tokens": 128, "temperature": 0.7},
        resolve=True
    )

    return improved_chunk, analyses

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
    guidance_chat = chat.clone()
    guidance_chat.assistant("")
    assistant_message = guidance_chat.tail

    while True:
        next_chunk, analyses = await continue_generation(
            chat=guidance_chat,
            llm=llm
        )
        if not next_chunk.strip():
            break

        assistant_message.content += next_chunk
        await llm.emit_message(next_chunk)
