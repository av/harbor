import { chalk } from './deps.ts';

export const forPrefix = (prefix: string) => ({
  child: (subPrefix: string) => child(`${prefix ? prefix + ':' : ''}${subPrefix}`),
});

const padZero = (number: number, count = 2) => number.toString().padStart(count, '0');

export const formatPrefix = (prefix: string) => {
  const now = new Date();
  const time = `${padZero(now.getHours())}:${padZero(now.getMinutes())}:${padZero(now.getSeconds())}:${padZero(
    now.getMilliseconds(),
    3,
  )}`;

  return `[${chalk.grey(time)}@${chalk.underline.green(prefix)}]`;
}

export const child = (prefix: string) => Object.assign((...args: any[]) => {
  console.info(formatPrefix(prefix), ...args);
}, forPrefix(prefix));

export const log = child('');

export default log;
