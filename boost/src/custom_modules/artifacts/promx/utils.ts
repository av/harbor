export function rnd(min?: number, max?: number | undefined) {
  if (min == null) {
    min = 1;
  }

  if (max == null) {
    max = min;
    min = 0;
  }
  return min + Math.random() * (max - min);
}

export function rndInt(min, max) {
  return Math.floor(rnd(min, max));
}

export function any(array) {
  return array[Math.floor(Math.random() * array.length)];
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function clamp01(value) {
  return clamp(value, 0, 1);
}

export function lerp(a, b, t) {
  return a + (b - a) * t;
}

export function lmap(value, inMin, inMax, outMin, outMax) {
  return outMin + ((value - inMin) * (outMax - outMin)) / (inMax - inMin);
}

export function hashCode(s: string) {
  if (s.length == 0) return 0;
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = (hash << 5) - hash + s.charCodeAt(i);
    hash |= 0; // Convert to 32bit integer
  }
  return hash;
}

export function normalizeColor(input) {
  let output = {
    r: input.r / 255,
    g: input.g / 255,
    b: input.b / 255,
  };
  return output;
}

export function wrap(value, min, max) {
  let range = max - min;
  if (range == 0) return min;
  return ((value - min) % range) + min;
}

export function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function sequence(actions: () => Promise<void>[]) {
  for (const action of actions) {
    await action();
  }
}