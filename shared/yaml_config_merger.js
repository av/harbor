import fs from 'fs';
import yaml from 'js-yaml';
import path from 'path';
import argparse from 'argparse';
import _ from 'lodash';

function readYaml(filePath) {
  return yaml.load(fs.readFileSync(filePath, 'utf8'));
}

function writeYaml(data, filePath) {
  fs.writeFileSync(filePath, yaml.dump(data, { flowLevel: -1 }));
}

function renderEnvVars(value) {
  if (typeof value === 'string') {
    const pattern = /\$\{([^}]+)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)/g;
    return value.replace(pattern, (match, p1, p2) => {
      const varName = p1 || p2;
      return process.env[varName] || match;
    });
  } else if (Array.isArray(value)) {
    return value.map(renderEnvVars);
  } else if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, renderEnvVars(v)])
    );
  } else {
    return value;
  }
}

function mergeYamlFiles(directory, pattern, outputFile) {
  let mergedData = {};

  fs.readdirSync(directory)
    .sort()
    .filter(filename => filename.endsWith(pattern))
    .forEach(filename => {
      const filePath = path.join(directory, filename);
      let yamlData = readYaml(filePath);
      yamlData = renderEnvVars(yamlData);
      mergedData = _.mergeWith(
        mergedData, yamlData, (objValue, srcValue) => {
          if (_.isArray(objValue)) {
            return objValue.concat(srcValue);
          }
        }
      );
    });

  ensureDir(path.dirname(outputFile));
  writeYaml(mergedData, outputFile);
}

function ensureDir(directory) {
  if (!fs.existsSync(directory)) {
    fs.mkdirSync(directory, { recursive: true });
  }
}

function main() {
  const parser = new argparse.ArgumentParser({
    description: 'Merge YAML files in a directory and render environment variables.'
  });
  parser.add_argument('--pattern', { default: '.yaml', help: 'File pattern to match (default: .yaml)' });
  parser.add_argument('--output', { default: 'merged_output.yaml', help: 'Output file name (default: merged_output.yaml)' });
  parser.add_argument('--directory', { default: '.', help: 'Directory to search for YAML files (default: current directory)' });

  const args = parser.parse_args();

  mergeYamlFiles(args.directory, args.pattern, args.output);
  console.log(`Merged YAML files matching '${args.pattern}' into '${args.output}' with environment variables rendered`);
}

main()