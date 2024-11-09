import { envNumber } from './utils.js';

export default {
  runs: {
    vus: envNumber('VUS', 1),
    // Uses K6 time notation: "1m", "10s", etc.
    timeWait: __ENV.TIME_WAIT,
    timeRampUp: __ENV.TIME_RAMP_UP,
    timeLoad: __ENV.TIME_LOAD,
    timeRampDown: __ENV.TIME_RAMP_DOWN,
  },
  ollama: {
    url: __ENV.OLLAMA_API_URL,
    key: __ENV.OLLAMA_API_KEY,
  }
};
