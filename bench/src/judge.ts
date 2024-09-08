export const prompt = ({
    question,
    answer,
    criteria,
}) => `
<instructions>
You will be given a criteria to evaluate an answser to a given question.
You must only respond with "Yes" if criteria is met or "No" otherwise.
</instructions>

<criteria>
${criteria}
</criteria>

<question>
${question}
</question>

<answer>
${answer}
</answer>
`

export const judge = {
    // model: 'llama3.1:8b',
    model: 'mistral-nemo:12b-instruct-2407-q8_0',
    // model: 'gemma2:latest',
    temperature: 0,
    prompt: ({ question, answer, criteria }) => `
  <your_instructions>
  You are an expert evaluating a Large Language Model. Model answered a question and you need to evaluate the quality of the answer.
  You will use following criteria to evaluate the response:
  ${criteria}
  Responses you receive are already very good and you won't offend anyone by being critical. Vice versa, by being stricter - you'll work for th good of humanity. So you need to be extra-critical.
  For every criteria, you will give a score from 1 (very good) to 10 (excellent).
  
  Your own response must be machine-readable. Ensure to strictly follow the format:
  - Category: "Completeness", Score: 5
  - Category: "Reasoning", Score: 2
  - Category: "Clarity", Score: 8
  Don't add anything else to your response. It's not personal.
  </your_instructions>
  
  <model_task>
  ${question}
  </model_task>
  
  <model_response>
  ${answer}
  </model_response>
    `,
    times: 5,
};