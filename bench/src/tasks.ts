export enum TaskTags {
  easy = 'easy',
  medium = 'medium',
  hard = 'hard',

  reasoning = 'reasoning',
  knowledge = 'knowledge',
  multitask = 'multitask',
  multilang = 'multilang',
  confabula = 'confabula',
}

export type Task = {
  question: string;
  criteria: Record<string, string>;
  tags: `${TaskTags}`[];

  // Optional, could be
  // present on semi-complete tasks
  time?: number;
  answer?: string;
  results?: Record<string, number>;
};

export const tasks: Task[] = [
  {
    tags: ["easy", 'knowledge'],
    question: 'Where is Minsk located?',
    criteria: {
      correctness: 'Answer mentions that Minsk is located in Belarus or is a capital of Belarus',
    }
  },
];
