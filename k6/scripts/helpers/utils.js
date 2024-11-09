/**
 * K6 runs a custom JS engine
 * that is not Node.js, so we can't really
 * use arbitrary external modules. Hence these utils.
 */

export function isObject(item) {
  return (item && typeof item === 'object' && !Array.isArray(item) && item !== null);
}

export const alphabet = 'qwertyuioplkjhgfdsamnbvcxz'.split('');

/**
 * Deep merge two objects.
 * @param target
 * @param source
 */
export function mergeDeep(target, source) {
  if (isObject(target) && isObject(source)) {
    Object.keys(source).forEach(key => {
      if (isObject(source[key])) {
        if (!target[key]) Object.assign(target, { [key]: {} });
        mergeDeep(target[key], source[key]);
      } else {
        Object.assign(target, { [key]: source[key] });
      }
    });
  }
  return target;
}

/**
 * Returns a parsed number for a given environment variable value,
 * if not available returns a provided default value.
 */
export function envNumber(key, defaultValue) {
  if (__ENV[key]) {
    const maybeValue = Number(__ENV[key])
    return Number.isNaN(maybeValue) ? defaultValue : maybeValue;
  }

  return defaultValue;
}

/**
 * Random integer between from and to,
 * if "to" is undefined, from 0 to "from"
 */
export const random = (from, to) => {
  if (!to) {
    to = from;
    from = 0;
  }

  return Math.round(
    from + (to - from) * Math.random(),
  );
};

/**
 * Returns a random element of a given array
 */
export const any = (arr) => arr[Math.floor(Math.random() * arr.length)];

/**
 * Returns true or false with given "probability"
 */
export const maybe = (probability = 0.5) => {
  if (Math.random() < probability) {
    return true;
  }

  return false;
}

/**
 * Returns a random sample from a given array
 *
 * @param {*[]} arr
 * @param {Number} count
 * @returns {*[]}
 */
export const sample = (arr, count = 1) => {
  const selection = [];
  let restItems = arr;

  while (count > 0) {
    const nextItem = any(restItems);

    selection.push(nextItem);
    restItems = restItems.filter((item) => item !== nextItem);
    count--;
  }

  return selection;
};

export const ts2s = (ts) => `${(ts / 1000).toFixed(1)}s`;

/**
 *
 * Returns true if the given endpoint is a local instance
 */
export function isLocalInstance(endpoint) {
  return /http(s)?:\/\/(.*\.docker\.|localhost)/i.test(endpoint)
}

export function chunks(arr, size) {
  return arr.reduce((acc, _, i) => {
    if (i % size === 0) {
      acc.push(arr.slice(i, i + size));
    }

    return acc;
  }, []);
}

export function permutate(a, b) {
  return a.reduce((acc, aItem) => {
    return acc.concat(b.map(bItem => `${aItem}-${bItem}`));
  }, []);
}

export function uniqueVariants(variations, duration) {
  const dimensions = Object.keys(variations);
  const wrapDimension = (dimension) => {
    return variations[dimension].map((v) => {
      if (v.includes('_')) {
        throw new Error(`Variation values cannot contain "_" variation: "${v}", dimension: "${dimension}"`);
      }

      return `${dimension}_${v}`;
    });
  };
  let variants = wrapDimension(dimensions[0]);

  for (let i = 1; i < dimensions.length; i++) {
    variants = permutate(variants, wrapDimension(dimensions[i]));
  }

  return variants;
}

/**
 * Pass in an object shaped like this:
 * {
 *   page: ['firstPage', 'randomPage'],
 *   sort: ['noSort', 'sort'],
 * }
 *
 * and it will return a set of K6 scenarios
 * to verify all possible combinations of these
 * variations together. In the example above:
 * - firstPage-noSort
 * - firstPage-sort
 * - randomPage-noSort
 * - randomPage-sort
 *
 * You can supply arbitrary number of variations,
 * but please keep in mind that the number of
 * scenarios will grow exponentially with each
 * additional variation.
 */
export function scenariosForVariations(variations, duration) {
  const variants = uniqueVariants(variations);

  return Object.fromEntries(
    variants.map((variant, i) => {
      return [variant, {
        executor: 'constant-vus',
        duration: `${duration}s`,
        startTime: `${i * duration}s`,
        env: parseVariation(variant),
      }];
    })
  );
}

/**
 * Similar to scenariosForVariations, but
 * accepts an array of specific pre-computed variants.
 *
 * @param {*} variants
 * @param {*} duration
 * @returns
 */
export function scenariosForVariants(variants, duration) {
  return Object.fromEntries(
    variants.map((variant, i) => {
      const key = Object.entries(variant).map(([k, v]) => `${k}_${v}`).join('-');

      return [key, {
        executor: 'constant-vus',
        duration: `${duration}s`,
        startTime: `${i * duration}s`,
        env: variant,
      }];
    })
  );
}

export function randomVariation(variations) {
  return Object.fromEntries(
    Object.entries(variations).map(([key, values]) => [key, any(values)])
  );
}

export function parseVariation(variation) {
  return variation.split('-').reduce((acc, item) => {
    const [key, value] = item.split('_');
    acc[key] = value;
    return acc;
  }, {});
}

export function between(value, from, to) {
  return value >= from && value <= to;
}


export function weightedOutcome(outcomes) {
  const weights = outcomes.map(([weight]) => weight);
  const total = weights.reduce((a, b) => a + b, 0);
  const target = random(0, total);
  const ranges = weights.reduce((acc, weight, index) => {
    const previousWeight = index === 0 ? 0 : acc[index - 1][0][1];
    acc.push([[previousWeight, previousWeight + weight], outcomes[index][1]]);
    return acc;
  }, []);

  return ranges.find(([range]) => between(target, range[0], range[1]))[1];
}

/**
 * Take scenarios and arrange them to run one by one
 */
export function sequenceScenarios(scenarios, duration) {
  return Object.fromEntries(
    Object.entries(scenarios).map(([scenario, config], i) => {
      return [scenario, {
        ...config,
        duration: `${duration}s`,
        startTime: `${i * duration}s`,
      }];
    }),
  );
}