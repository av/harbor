import { LLM } from "./llm.ts"
import { prefixKeys, squash } from "./utils.ts";
import { config } from './config.ts';
import { BenchTask } from "./task.ts";

export class BenchRun {
  llm: LLM;
  judge: LLM;
  tasks: BenchTask[];

  constructor({
    llm,
    judge,
    tasks,
  }: {
    llm: LLM,
    judge: LLM,
    tasks: BenchTask[],
  }) {
    this.llm = llm;
    this.judge = judge;
    this.tasks = tasks;
  }

  async run() {
    console.log('Running tasks...');
    await this.processTasks(this.tasks, (task) => task.run(this.llm));
  }

  async eval() {
    console.log('Evaluating results...');
    await this.processTasks(this.tasks, (task) => task.eval(this.judge));
  }

  private async processTasks(tasks: BenchTask[], action: (task: BenchTask) => Promise<void>) {
    const total = tasks.length;
    let done = 0;
    const queue = [...tasks];
    const runningTasks = new Set<Promise<void>>();

    while (queue.length > 0 || runningTasks.size > 0) {
      while (runningTasks.size < config.parallel && queue.length > 0) {
        const task = queue.shift()!;
        const taskPromise = (async () => {
          await action(task);
          console.log(`[${++done}/${total}]`);
          runningTasks.delete(taskPromise);
        })();
        runningTasks.add(taskPromise);
      }

      if (runningTasks.size > 0) {
        await Promise.race(runningTasks);
      }
    }
  }

  toJson() {
    return {
      llm: this.llm,
      judge: this.judge,
      tasks: this.tasks,
    };
  }

  toResults() {
    // Flatten for RAWGraphs.io
    const llm = prefixKeys('llm', squash(this.llm.toJson()));
    const judge = prefixKeys('judge', squash(this.judge.toJson()));
    const base = {
      ...llm,
      ...judge,
      name: config.name,
    };

    return this.tasks.flatMap((t, i) => {
      const results = t.criteria;

      return Object.entries(results).map(([k]) => {
        const id = `task.${i}.${k}`;
        const result = t.results[k];

        return {
          id,
          result,
          tags: t.tags,
          ...base,
        };
      });
    });
  }
};
