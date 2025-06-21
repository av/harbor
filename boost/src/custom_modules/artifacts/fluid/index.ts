// Credits:
// 1. Most of the smoke simulation code is adapted from
// https://paveldogreat.github.io/WebGL-Fluid-Simulation/
// 2. D3.js for the force simulation

"use strict";

import { rnd, lmap, sleep } from "./utils";
import { Visualisation } from './visualisation';


document.addEventListener("DOMContentLoaded", async () => {
  const vis = new Visualisation();
  await vis.init();

  // Local test
  // vis.listener.emit('boost.concept', { concept: 'Greeting' });
  // vis.listener.emit('boost.concept', { concept: 'Comradery' });
  // await sleep(1000);
  // vis.listener.emit('boost.intensity', { intensity: 0.05 });
  // await sleep(1000);
  // vis.listener.emit('boost.linked_concepts', { concepts: ['Greeting', 'Comradery'] });
  // await sleep(1000);
  // vis.listener.emit('boost.concept', { concept: 'Innovation' });
  // await sleep(1000);
  // vis.listener.emit('boost.concept', { concept: 'Empathy' });
  // await sleep(1000);
  // vis.listener.emit('boost.concept', { concept: 'Collaboration' });
})
