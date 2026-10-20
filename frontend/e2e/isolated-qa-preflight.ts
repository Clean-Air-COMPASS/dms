import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const ARTIFACTS_ROOT = resolve(REPOSITORY_ROOT, 'artifacts');
const REQUIRED_SERVICES = ['api', 'db', 'frontend', 'scheduler'] as const;

type ComposeService = {
  container_name?: string;
  environment?: Record<string, string | null>;
  networks?: Record<string, unknown>;
  ports?: { host_ip?: string; published?: string; protocol?: string; target?: number }[];
  volumes?: { source?: string; type?: string }[];
};

type ContainerInspection = {
  Name: string;
  Config: { Labels: Record<string, string> };
  State: { Running: boolean };
  Mounts: { Type: string; Name?: string }[];
  NetworkSettings: {
    Networks: Record<string, unknown>;
    Ports: Record<string, { HostIp: string; HostPort: string }[] | null>;
  };
};

export type IsolatedQaTarget = {
  baseUrl: string;
  outputDir: string;
  project: string | null;
  dockerContext: string | null;
  databaseContainerId: string | null;
};

function requiredEnvironment(name: string) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`[Playwright preflight] ${name} is required; no browser was started.`);
  }
  return value;
}

function artifactPath(name: string, value: string) {
  const fullPath = resolve(REPOSITORY_ROOT, value);
  const relativePath = relative(ARTIFACTS_ROOT, fullPath);
  if (!relativePath || relativePath === '..' || relativePath.startsWith(`..${sep}`)) {
    throw new Error(`[Playwright preflight] ${name} must be inside this run's artifacts directory.`);
  }
  return fullPath;
}

function outputDirectory(strict: boolean) {
  const configuredPath = process.env.QC_E2E_OUTPUT_DIR?.trim();
  if (strict && !configuredPath) {
    throw new Error('[Playwright preflight] QC_E2E_OUTPUT_DIR is required; no browser was started.');
  }
  const fullPath = configuredPath
    ? artifactPath('QC_E2E_OUTPUT_DIR', configuredPath)
    : resolve(ARTIFACTS_ROOT, `playwright-${Date.now()}`);
  const runToken = process.env.QC_E2E_RUN_TOKEN?.trim();
  const configuredMarker = process.env.QC_E2E_RUN_MARKER_FILE?.trim();
  // Keep the runner marker beside the output directory because Playwright clears that directory before reloading config in workers.
  const runMarker = configuredMarker ? artifactPath('QC_E2E_RUN_MARKER_FILE', configuredMarker) : '';
  const markerRelativeToOutput = runMarker ? relative(fullPath, runMarker) : '';
  if (runMarker && (markerRelativeToOutput === '' ||
      (!markerRelativeToOutput.startsWith('..') && !markerRelativeToOutput.startsWith(sep)))) {
    throw new Error('[Playwright preflight] The runner marker must be outside the Playwright output directory.');
  }
  const runMarkerContent = runMarker && existsSync(runMarker) ? readFileSync(runMarker, 'utf8') : '';
  const runnerOwnsDirectory = Boolean(
    runToken && runMarker && runMarkerContent === runToken,
  );
  if (existsSync(fullPath) && readdirSync(fullPath).length > 0 && !runnerOwnsDirectory) {
    throw new Error('[Playwright preflight] Choose a new empty output directory so earlier QA evidence is preserved.');
  }
  mkdirSync(fullPath, { recursive: true });
  return fullPath;
}

function runDocker(context: string, args: string[], purpose: string) {
  try {
    return execFileSync('docker', ['--context', context, ...args], { encoding: 'utf8' }).trim();
  } catch {
    throw new Error(`[Playwright preflight] Docker could not verify ${purpose}; no browser was started.`);
  }
}

function inspectContainer(context: string, id: string) {
  return JSON.parse(runDocker(context, ['inspect', id], 'the QA containers'))[0] as ContainerInspection;
}

function validateIsolatedQaProject(baseUrl: string, outputDir: string): IsolatedQaTarget {
  const project = requiredEnvironment('CSV_QA_COMPOSE_PROJECT');
  const qaBaseUrl = requiredEnvironment('CSV_QA_BASE_URL');
  const dockerContext = requiredEnvironment('CSV_QA_DOCKER_CONTEXT');
  const envFile = artifactPath('CSV_QA_ENV_FILE', requiredEnvironment('CSV_QA_ENV_FILE'));
  const overrideFile = artifactPath(
    'CSV_QA_COMPOSE_OVERRIDE_FILE',
    requiredEnvironment('CSV_QA_COMPOSE_OVERRIDE_FILE'),
  );
  const fixturePath = artifactPath('CSV_QA_FIXTURE', requiredEnvironment('CSV_QA_FIXTURE'));

  if (!/^compassaq-restart-[a-z0-9-]+$/.test(project)) {
    throw new Error('[Playwright preflight] CSV_QA_COMPOSE_PROJECT must identify a dedicated compassaq-restart-* project.');
  }
  if (qaBaseUrl !== baseUrl) {
    throw new Error('[Playwright preflight] QC_E2E_BASE_URL must exactly match CSV_QA_BASE_URL.');
  }
  for (const file of [envFile, overrideFile, fixturePath]) {
    if (!existsSync(file)) {
      throw new Error('[Playwright preflight] A required QA-only Compose or credential fixture file is missing.');
    }
  }

  let fixture: { email?: string; password?: string };
  try {
    fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as { email?: string; password?: string };
  } catch {
    throw new Error('[Playwright preflight] CSV_QA_FIXTURE must contain the synthetic QA account.');
  }
  if (
    !/^synthetic-csv-qa-[0-9a-f]{8}@example\.com$/i.test(fixture.email ?? '') ||
    typeof fixture.password !== 'string' || fixture.password.length < 24
  ) {
    throw new Error('[Playwright preflight] Browser credentials must come from the disposable synthetic QA fixture.');
  }

  const baseComposeFile = resolve(REPOSITORY_ROOT, 'docker-compose.yml');
  let composeConfig: {
    name?: string;
    networks?: Record<string, { external?: boolean; name?: string }>;
    services?: Record<string, ComposeService>;
    volumes?: Record<string, { external?: boolean; name?: string }>;
  };
  try {
    const output = runDocker(dockerContext, [
      'compose', '-p', project, '--env-file', envFile,
      '-f', baseComposeFile, '-f', overrideFile, 'config', '--format', 'json',
    ], 'the resolved QA Compose configuration');
    composeConfig = JSON.parse(output) as typeof composeConfig;
  } catch {
    throw new Error('[Playwright preflight] The QA Compose configuration could not be resolved; no browser was started.');
  }

  if (composeConfig.name !== project || !composeConfig.services || !composeConfig.networks?.default) {
    throw new Error('[Playwright preflight] The resolved Compose project identity or default network is incorrect.');
  }
  const network = composeConfig.networks.default;
  if (network.external || !network.name?.startsWith(`${project}_`)) {
    throw new Error('[Playwright preflight] The resolved network must be owned by the QA Compose project.');
  }

  const volumes = Object.values(composeConfig.volumes ?? {});
  if (!volumes.length || volumes.some(volume => volume.external || !volume.name?.startsWith(`${project}_`))) {
    throw new Error('[Playwright preflight] Resolved database and runtime volumes must be unique to the QA project.');
  }

  const services = composeConfig.services;
  if (Object.keys(services).sort().join(',') !== [...REQUIRED_SERVICES].sort().join(',')) {
    throw new Error('[Playwright preflight] The QA Compose project must contain only frontend, API, scheduler, and database services.');
  }
  for (const serviceName of REQUIRED_SERVICES) {
    const service = services[serviceName];
    if (!service.container_name?.startsWith(`${project}-`)) {
      throw new Error(`[Playwright preflight] The ${serviceName} container name must belong to the QA project.`);
    }
    if (Object.keys(service.networks ?? {}).join(',') !== 'default') {
      throw new Error(`[Playwright preflight] The ${serviceName} container must use only the QA network.`);
    }
    if (service.volumes?.some(volume => volume.type === 'bind')) {
      throw new Error(`[Playwright preflight] The ${serviceName} container must not mount a development checkout.`);
    }
    if (serviceName !== 'frontend' && (service.ports?.length ?? 0) > 0) {
      throw new Error(`[Playwright preflight] The ${serviceName} service must not publish a host port.`);
    }
  }

  const apiEnvironment = services.api.environment ?? {};
  const schedulerEnvironment = services.scheduler.environment ?? {};
  for (const [serviceName, environment] of [['api', apiEnvironment], ['scheduler', schedulerEnvironment]] as const) {
    if (environment.COMPASSAQ_ENV !== 'development' || String(environment.DISABLE_PAID_API_REQUESTS).toLowerCase() !== 'true') {
      throw new Error(`[Playwright preflight] The ${serviceName} must use the QA environment with paid provider requests disabled.`);
    }
    if (Object.entries(environment).some(([name, value]) =>
      /^(OPENAQ|PURPLEAIR|AIRGRADIENT|AIRNOW|AQICN|GEOAPIFY)_.*(API_KEY|TOKEN)$/i.test(name) && Boolean(value?.trim())
    )) {
      throw new Error(`[Playwright preflight] The ${serviceName} contains a provider credential; no browser was started.`);
    }
  }

  const url = new URL(baseUrl);
  const frontendPorts = services.frontend.ports ?? [];
  if (
    frontendPorts.length !== 1 || frontendPorts[0].host_ip !== '127.0.0.1' ||
    Number(frontendPorts[0].published) !== Number(url.port) || frontendPorts[0].target !== 80
  ) {
    throw new Error('[Playwright preflight] The QA URL does not match the resolved loopback frontend port.');
  }

  const containerIds = runDocker(dockerContext, [
    'ps', '-aq', '--filter', `label=com.docker.compose.project=${project}`,
  ], 'the QA Compose containers').split(/\r?\n/).filter(Boolean);
  if (containerIds.length !== REQUIRED_SERVICES.length) {
    throw new Error('[Playwright preflight] The QA project must have exactly four application containers.');
  }

  const seenServices = new Set<string>();
  let databaseContainerId = '';
  for (const id of containerIds) {
    const container = inspectContainer(dockerContext, id);
    const labels = container.Config.Labels;
    const serviceName = labels['com.docker.compose.service'];
    if (
      labels['com.docker.compose.project'] !== project ||
      !REQUIRED_SERVICES.includes(serviceName as typeof REQUIRED_SERVICES[number]) || seenServices.has(serviceName)
    ) {
      throw new Error('[Playwright preflight] A container does not match the explicit QA project and service identity.');
    }
    seenServices.add(serviceName);
    if (serviceName === 'db') databaseContainerId = id;
    if (!container.State.Running || container.Name !== `/${services[serviceName].container_name}`) {
      throw new Error(`[Playwright preflight] The ${serviceName} container is stopped or has an unexpected name.`);
    }
    if (labels['com.docker.compose.project.config_files']?.split(',').length !== 2) {
      throw new Error(`[Playwright preflight] The ${serviceName} container was not created from the verified Compose files.`);
    }

    const networkNames = Object.keys(container.NetworkSettings.Networks);
    if (networkNames.length !== 1 || networkNames[0] !== network.name) {
      throw new Error(`[Playwright preflight] The ${serviceName} container is attached outside the QA network.`);
    }
    const networkDetails = JSON.parse(runDocker(dockerContext, ['network', 'inspect', network.name], 'the QA network'))[0] as {
      Labels?: Record<string, string>;
      Name: string;
    };
    if (networkDetails.Name !== network.name || networkDetails.Labels?.['com.docker.compose.project'] !== project) {
      throw new Error('[Playwright preflight] The target network is not owned by the QA Compose project.');
    }
    if (container.Mounts.some(mount => mount.Type !== 'volume' || !mount.Name?.startsWith(`${project}_`))) {
      throw new Error(`[Playwright preflight] The ${serviceName} container has a shared or bind-mounted volume.`);
    }

    const publishedPorts = Object.values(container.NetworkSettings.Ports).flatMap(ports => ports ?? []);
    if (serviceName === 'frontend') {
      const matchingPorts = publishedPorts.filter(port =>
        port.HostIp === '127.0.0.1' && Number(port.HostPort) === Number(url.port),
      );
      if (publishedPorts.length !== 1 || matchingPorts.length !== 1) {
        throw new Error('[Playwright preflight] The explicit QA URL does not resolve to its task-owned frontend container.');
      }
    } else if (publishedPorts.length > 0) {
      throw new Error(`[Playwright preflight] The ${serviceName} container unexpectedly publishes a host port.`);
    }
  }

  for (const volume of volumes) {
    const details = JSON.parse(runDocker(dockerContext, ['volume', 'inspect', volume.name!], 'the QA volumes'))[0] as {
      Labels?: Record<string, string>;
    };
    if (details.Labels?.['com.docker.compose.project'] !== project) {
      throw new Error('[Playwright preflight] A named volume is not owned by the QA Compose project.');
    }
  }
  if (seenServices.size !== REQUIRED_SERVICES.length || !databaseContainerId) {
    throw new Error('[Playwright preflight] The QA Compose project is missing a required application service.');
  }

  return { baseUrl, outputDir, project, dockerContext, databaseContainerId };
}

export function validatePlaywrightTarget(): IsolatedQaTarget {
  const baseUrl = requiredEnvironment('QC_E2E_BASE_URL');
  let target: URL;
  try {
    target = new URL(baseUrl);
  } catch {
    throw new Error('[Playwright preflight] QC_E2E_BASE_URL must be an explicit loopback HTTP URL.');
  }
  if (
    target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || !target.port ||
    target.port === '80' || target.username || target.password || target.pathname !== '/' || target.search || target.hash
  ) {
    throw new Error('[Playwright preflight] QC_E2E_BASE_URL must be http://127.0.0.1:<isolated-port>, never the port-80 development fallback.');
  }

  const strict = process.env.QC_E2E_REQUIRE_COMPOSE_PREFLIGHT === '1' || Boolean(process.env.CSV_QA_COMPOSE_PROJECT);
  const outputDir = outputDirectory(strict);
  return strict
    ? validateIsolatedQaProject(baseUrl, outputDir)
    : { baseUrl, outputDir, project: null, dockerContext: null, databaseContainerId: null };
}

export function getIsolatedDatabaseContainerId() {
  const project = requiredEnvironment('CSV_QA_COMPOSE_PROJECT');
  const dockerContext = requiredEnvironment('CSV_QA_DOCKER_CONTEXT');
  const ids = runDocker(dockerContext, [
    'ps', '-q', '--filter', `label=com.docker.compose.project=${project}`,
    '--filter', 'label=com.docker.compose.service=db',
  ], 'the isolated QA database').split(/\r?\n/).filter(Boolean);
  if (ids.length !== 1) {
    throw new Error('[Playwright preflight] The isolated QA database container is not uniquely identified.');
  }
  const database = inspectContainer(dockerContext, ids[0]);
  if (
    !database.State.Running || database.Config.Labels['com.docker.compose.project'] !== project ||
    database.Config.Labels['com.docker.compose.service'] !== 'db'
  ) {
    throw new Error('[Playwright preflight] The isolated QA database container is not running under the expected project.');
  }
  return { dockerContext, databaseContainerId: ids[0] };
}

export function getDatabaseMeasurementCount(databaseContainerId: string, dockerContext: string) {
  const output = runDocker(dockerContext, [
    'exec', databaseContainerId, 'sh', '-lc',
    'PGPASSWORD="$POSTGRES_PASSWORD" psql --host=127.0.0.1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-password --tuples-only --no-align --command="SELECT COUNT(*) FROM measurement;"',
  ], 'the isolated QA measurement count');
  if (!/^\d+$/.test(output)) {
    throw new Error('[Playwright preflight] Could not read the isolated QA measurement count.');
  }
  return Number(output);
}
