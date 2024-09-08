import { prompt } from "./judge.ts";

import type { Task } from "./tasks.ts";
import type { LLM } from "./llm.ts";

export class BenchTask implements Task {
  question: string;
  criteria: Record<string, string>;
  tags: Task['tags'];

  answer: string;
  results: Record<string, number>;

  constructor(task: Task) {
    this.question = task.question;
    this.criteria = task.criteria;
    this.tags = task.tags;

    this.answer = '';
    this.results = {};
  }

  async run(llm: LLM) {
    this.answer = await llm.chat(this.question);
  }

  async eval(judge: LLM) {
    for (const [key, value] of Object.entries(this.criteria)) {
      const result = await judge.chat(
        prompt({
          question: this.question,
          answer: this.answer,
          criteria: value
        })
      );

      this.results[key] = result.toLocaleLowerCase().includes('yes') ? 1 : 0;
    }
  }

  toJson() {
    return {
      question: this.question,
      answer: this.answer,
      tags: this.tags,
      criteria: this.criteria,
      results: this.results,
    };
  }
}