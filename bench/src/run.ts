import { LLM } from "./llm.ts"
import { formatTime, prefixKeys, squash } from "./utils.ts";
import { config } from './config.ts';
import { BenchTask } from "./task.ts";
import { log as logger } from "./log.ts";

const log = logger.child('run');

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
    log('Running tasks...');
    await this.processTasks(this.tasks, (task) => task.run(this.llm));
  }

  async eval() {
    log('Evaluating results...');
    await this.processTasks(this.tasks, (task) => task.eval(this.judge));
  }

  private async processTasks(tasks: BenchTask[], action: (task: BenchTask) => Promise<void>) {
    const total = tasks.length;
    let done = 0;
    const queue = [...tasks];
    const runningTasks = new Set<Promise<void>>();
    const recentTaskTimes: number[] = [];
    const recentTasksToTrack = Math.max(Math.ceil(total * 0.05), 1); // % of total, minimum 1

    while (queue.length > 0 || runningTasks.size > 0) {
      while (runningTasks.size < config.parallel && queue.length > 0) {
        const task = queue.shift()!;
        const taskStartTime = Date.now();
        const taskPromise = (async () => {
          await action(task);
          runningTasks.delete(taskPromise);
          done++;

          const taskDuration = (Date.now() - taskStartTime) / 1000; // in seconds
          recentTaskTimes.push(taskDuration);
          if (recentTaskTimes.length > recentTasksToTrack) {
            recentTaskTimes.shift(); // Remove oldest task time
          }

          const averageRecentTaskTime = recentTaskTimes.reduce((a, b) => a + b, 0) / recentTaskTimes.length;
          const remainingTasks = total - done;
          const estimatedRemainingTime = averageRecentTaskTime * remainingTasks;

          const remainingTimeStr = formatTime(estimatedRemainingTime);

          log(`[${done}/${total}], q(${queue.length}), r(${runningTasks.size}), ETA: ${remainingTimeStr}`);
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
        const id = `task.${i + 1}.${k}`;
        const result = t.results[k];

        return {
          id,
          result,
          tags: t.tags,
          time: t.time,
          ...base,
        };
      });
    });
  }
};
