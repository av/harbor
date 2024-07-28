import path from 'path';

const root = path.resolve('/home/circleci/workspace');

export const paths = {
  root,
  git: resolve('.git'),
  pkg: resolve('package.json'),
};

export function resolve(subpath: string) {
  return path.resolve(root, subpath);
};