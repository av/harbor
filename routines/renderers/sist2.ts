import type { ServiceRenderer, ServiceRendererContext } from '../types';
import { getValue } from '../envManager';
import { log } from '../utils';
import path from 'node:path';

export const handle = 'sist2';

function pathToMountName(hostPath: string, index: number, existingNames: Set<string>): string {
  let baseName = path.basename(hostPath);

  if (!baseName || baseName === '/') {
    baseName = `volume_${index}`;
  }

  let finalName = baseName;
  let counter = 1;

  while (existingNames.has(finalName)) {
    finalName = `${baseName}_${counter}`;
    counter++;
  }

  existingNames.add(finalName);
  return finalName;
}

const renderer: ServiceRenderer = async (ctx: ServiceRendererContext) => {
  const { serviceConfig } = ctx;

  const scanPathsRaw = await getValue({ key: 'sist2.scan.paths' });

  if (!scanPathsRaw || scanPathsRaw.trim() === '') {
    log.debug('sist2: No scan paths configured');
    return;
  }

  const scanPaths = scanPathsRaw
    .split(';')
    .map((p) => p.trim())
    .filter((p) => p.length > 0);

  if (scanPaths.length === 0) {
    log.debug('sist2: Empty scan paths after parsing');
    return;
  }

  if (!serviceConfig.volumes) {
    serviceConfig.volumes = [];
  }

  const existingNames = new Set<string>();

  for (const vol of serviceConfig.volumes) {
    const containerPath = vol.split(':')[1];
    if (containerPath?.startsWith('/host/')) {
      existingNames.add(containerPath.replace('/host/', ''));
    }
  }

  for (let i = 0; i < scanPaths.length; i++) {
    const hostPath = scanPaths[i];
    const mountName = pathToMountName(hostPath, i, existingNames);
    const volumeMount = `${hostPath}:/host/${mountName}:ro`;

    if (!serviceConfig.volumes.includes(volumeMount)) {
      serviceConfig.volumes.push(volumeMount);
      log.debug(`sist2: Added volume mount: ${volumeMount}`);
    }
  }
};

export default renderer;
