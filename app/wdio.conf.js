import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'

const osName = os.platform()

export const config = {
  specs: ['./test/specs/**/*.js'],
  maxInstances: 1,
  capabilities: [
    {
      maxInstances: 1,
      browserName: 'chrome',
      'goog:chromeOptions': {
        args: ['--headless', '--disable-gpu']
      },
      'tauri:options': {
        application: path.join(
          process.cwd(),
          'src-tauri',
          'target',
          'release',
          osName === 'darwin'
            ? 'harbor-app.app/Contents/MacOS/harbor-app'
            : osName === 'win32'
            ? 'harbor-app.exe'
            : 'harbor-app'
        )
      }
    }
  ],
  logLevel: 'trace',
  bail: 0,
  waitforTimeout: 10000,
  connectionRetryTimeout: 120000,
  connectionRetryCount: 3,
  framework: 'mocha',
  reporters: ['spec'],
  mochaOpts: {
    ui: 'bdd',
    timeout: 60000
  },
  services: []
}
