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
`;