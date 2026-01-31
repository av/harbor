import { any, sample } from '../helpers/utils.js';

const countries = [
  'France', 'Poland', 'Japan', 'USA',
]

export const qwenOneWord = () => ({
  model: 'qwen2.5:1.5b-instruct-q8_0',
  temperature: 0,
  seed: 0,
  messages: [
    {
      role: 'user',
      content: `Reply in one word. What is the capital of ${any(countries)}?`,
    },
  ]
})

export const qwenNumSeq = ({ size }) => {
  const num = () => (Math.random() * 100).toFixed(0);
  const nums = Array(size).fill(0).map(() => num()).join(' ');

  return ({
    model: 'qwen2.5:1.5b-instruct-q8_0',
    temperature: 0,
    seed: 0,
    messages: [
      {
        role: 'user',
        content: `${nums}. Guess the next number. Reply with the number and nothing else.`,
      },
    ]
  })
}