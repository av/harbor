export function isObject(obj: unknown) {
  return obj && typeof obj === 'object';
};

export function uniqueVariants<T>(variations: Record<string, string[]>): T[] {
  const dimensions = Object.keys(variations).sort();
  if (dimensions.length === 0) return [];

  const dimension = (name: string) => variations[name].map((v) => ({ [name]: v }));
  let variants = dimension(dimensions[0]);

  for (let i = 1; i < dimensions.length; ++i) {
    variants = permutate(variants, dimension(dimensions[i]));
  }

  return variants.map((opts) => {
    if (Array.isArray(opts)) {
      return deepMerge(...opts);
    }

    return opts;
  });
}

export function omit(obj: Object, keys: string[]) {
  return Object.fromEntries(Object.entries(obj).filter(([key]) => !keys.includes(key)));
}

export function permutate(a: any[], b: any[]): any[] {
    return a.reduce((acc, aItem) => {
        if (b.length > 0) {
          return acc.concat(b.map(bItem => [aItem, bItem].flat()));
        }

        return acc.concat([aItem]);
    }, []);
}

export function clone<T extends unknown>(obj: T): T {
  if (obj === null || typeof obj !== 'object') {
    return obj;
  }

  if (obj instanceof Date) {
    return new Date(obj.getTime()) as T;
  }

  if (obj instanceof Array) {
    return obj.map(item => clone(item)) as T;
  }

  if (obj instanceof Object) {
    const clonedObj: Record<string, any> = {};
    for (const key in obj) {
      if (obj.hasOwnProperty(key)) {
        clonedObj[key] = clone(obj[key]);
      }
    }
    return clonedObj as T;
  }

  throw new Error('Unable to clone object. Unsupported type.');
}

export function deepMerge(...objects: any[]): any {
  return objects.reduce((prev, obj) => {
    Object.keys(obj).forEach(key => {
      const pVal = prev[key];
      const oVal = obj[key];

      if (Array.isArray(pVal) && Array.isArray(oVal)) {
        prev[key] = pVal.concat(...oVal);
      }
      else if (isObject(pVal) && isObject(oVal)) {
        prev[key] = deepMerge(pVal, oVal);
      }
      else {
        prev[key] = oVal;
      }
    });
    return prev;
  }, {});
}

export function squash(object: any): any {
  const result: Record<string, any> = {};

  function flatten(current: any, parentKey = '') {
    for (const key in current) {
      if (current.hasOwnProperty(key)) {
        const newKey = parentKey ? `${parentKey}.${key}` : key;
        if (typeof current[key] === 'object' && current[key] !== null && !Array.isArray(current[key])) {
          flatten(current[key], newKey);
        } else {
          result[newKey] = current[key];
        }
      }
    }
  }

  flatten(object);

  return result;
}

export function prefixKeys(prefix: string, object: any): any {
  return Object.fromEntries(
    Object.entries(object).map(([key, value]) => [
      `${prefix}.${key}`,
      value,
    ])
  );
}

export type DeepPartial<T> = { [P in keyof T]?: DeepPartial<T[P]> };



export function parseArgs(args: string[]) {
  return args.reduce((acc, arg, index, array) => {
    if (typeof arg !== 'string') {
      throw new Error(`Argument must be a string, instead got: ${arg}`);
    }

    if (arg.startsWith('--')) {
      const argName = arg.slice(2);
      const [name, value] = argName.includes('=') ? argName.split('=') : [argName, undefined];

      if (value !== undefined) {
        // If the argument has a value after '='
        if (name in acc) {
          acc[name] = Array.isArray(acc[name]) ? [...acc[name], value] : [acc[name], value];
        } else {
          acc[name] = value;
        }
      } else {
        // If the argument doesn't have a value, look at the next argument
        const nextArg = array[index + 1];
        if (nextArg && !nextArg.startsWith('--')) {
          if (name in acc) {
            acc[name] = Array.isArray(acc[name]) ? [...acc[name], nextArg] : [acc[name], nextArg];
          } else {
            acc[name] = nextArg;
          }
          array[index + 1] = ''; // Mark the next arg as processed
        } else {
          if (name in acc) {
            acc[name] = Array.isArray(acc[name]) ? [...acc[name], true] : [acc[name], true];
          } else {
            acc[name] = true;
          }
        }
      }
    } else if (arg !== '') { // Changed from '--PROCESSED--' to ''
      // Handle non-flag arguments
      const lastArgName = Object.keys(acc).pop();
      if (lastArgName && acc[lastArgName] === true) {
        acc[lastArgName] = arg;
      } else {
        // If there's no previous flag, add it to a special '_' key
        if ('_' in acc) {
          acc['_'] = Array.isArray(acc['_']) ? [...acc['_'], arg] : [acc['_'], arg];
        } else {
          acc['_'] = arg;
        }
      }
    }

    return acc;
  }, {} as Record<string, string | string[] | boolean>);
}

export const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export const formatTime = (seconds: number): string => {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.round(seconds % 60);

  const parts = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (remainingSeconds > 0) parts.push(`${remainingSeconds}s`);

  return parts.join(' ');
}