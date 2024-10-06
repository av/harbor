import { prompts } from "./judge.ts";

import type { Task } from "./tasks.ts";
import type { LLM } from "./llm.ts";

export class BenchTask implements Task {
  question: string;
  criteria: Record<string, string>;
  tags: Task['tags'];
  time: number;

  answer: string;
  results: Record<string, number>;

  constructor(task: Task) {
    this.question = task.question;
    this.criteria = task.criteria;
    this.tags = task.tags;

    this.answer = task.answer ?? '';
    this.results = task.results ?? {};
    this.time = task.time ?? 0;
  }

  async run(llm: LLM) {
    const start = Date.now();
    this.answer = await llm.chat(this.question);
    this.time = Date.now() - start;
  }

  async eval(judge: LLM) {
    for (const [key, value] of Object.entries(this.criteria)) {
      const prompt = prompts[judge.llm.prompt ?? 'default'] ?? prompts.default;
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
      time: this.time,
    };
  }
}