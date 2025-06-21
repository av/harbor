import fs from 'node:fs';
import path from 'node:path';
import inline from 'npm:web-resource-inliner';

const [dir, file] = Deno.args;
const filebase = file.split('.').slice(0, -1).join('.');
const filepath = path.join(dir, file);


inline
  .html({
    fileContent: fs.readFileSync(filepath, 'utf-8'),
    relativeTo: dir,
  }, (err, result) => {
    if (err) { throw err; }
    return fs.writeFileSync(`${dir}/${filebase}_built.html`, result);
  })