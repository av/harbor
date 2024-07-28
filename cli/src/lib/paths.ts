import path from 'path';

const root = path.resolve(__dirname, '../../');

export const paths = {
  root,
  workspace: '/home/circleci/workspace',
  workspaceGit: '/home/circleci/workspace/.git',
};

export function resolve(subpath: string) {
  return path.resolve(root, subpath);
};