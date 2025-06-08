import fs from 'node:fs';
import inline from 'npm:web-resource-inliner';

const srcDir = './boost/src/custom_modules/artifacts/fluid/dist';
const srcFile = `${srcDir}/index.html`;

inline
  .html({
    fileContent: fs.readFileSync(srcFile, 'utf-8'),
    relativeTo: srcDir,
  }, (err, result) => {
    if (err) { throw err; }
    return fs.writeFileSync(`${srcDir}/fluid_built.html`, result);
  })