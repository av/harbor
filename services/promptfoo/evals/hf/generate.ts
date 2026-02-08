// deno -A generate.ts

import { DuckDBInstance } from "npm:@duckdb/node-api";
import { stringify } from "jsr:@std/yaml";

import * as queries from './queries';

const db = await DuckDBInstance.create(":memory:");
const conn = await db.connect();

conn.run("INSTALL httpfs;");
conn.run("LOAD httpfs;");

const datasetUrl = "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/resolve/main/data/test-00000-of-00001.parquet";
const query = queries.challengingQuestions;
const outputName = "challenge.yaml";

conn.run(`CREATE TABLE test AS SELECT * FROM read_parquet('${datasetUrl}');`);

const reader = await conn.runAndReadAll(query);
const rows = reader.getRowObjectsJson();
const indexToLetter = (index: number) => {
  if (typeof index === 'string') {
    index = parseInt(index, 10);
  }

  return String.fromCharCode(65 + index)
};

const promptfooTests = rows.map((row) => {
  const questionText = `${row.question}\n\nOptions:\n${row.options.map((opt, index) => `${indexToLetter(index)}) ${opt.trim()}`).join('\n')}`;
  const expectedAnswer = `The final answer is \"${indexToLetter(row.answer_index)})\"`;

  return {
    vars: {
      question_id: row.question_id,
      question: questionText,
    },
    assert: [
      {
        type: "llm-rubric",
        value: expectedAnswer,
      },
//       {
//         type: "llm-rubric",
//         value: `
// The expected answer is "${indexToLetter(row.answer_index)})".
// Evaluate the output based on how close it is to the expected answer.

// Score of 0.0 - Output shows no connection to the expected answer.
// Score of 0.25 - Output is not correct but shows understanding of the question.
// Score of 0.5 - Output is partially correct, but does not match the expected answer.
// Score of 0.75 - Output is one mistake away from the expected answer.
// Score of 1.0 - Output matches the expected answer exactly.
//         `
//       }
    ],
  };
});

const yamlContent = stringify(promptfooTests);
const yamlHeader = `# Generated Promptfoo test cases for MMLU-Pro dataset
# This file contains test cases for evaluating LLMs on the MMLU-Pro dataset.
# Each test case includes a question with options and the expected answer.
`;
const yamlContentWithHeader = yamlHeader + yamlContent;
await Deno.writeTextFile(`./tests/${outputName}`, yamlContentWithHeader);

console.log(`Successfully generated Promptfoo test cases and saved to ${outputName}`);

conn.closeSync();