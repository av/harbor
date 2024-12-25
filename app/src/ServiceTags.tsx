import { IconAudioLines, IconAward, IconBandage } from "./Icons";
import { HarborService } from "./serviceMetadata";
import './tags.css';

// aka Harbor Service Tag
export enum HST {
  backend = "Backend",
  frontend = "Frontend",
  satellite = "Satellite",
  api = "API",
  cli = "CLI",
  partial = "Partial Support",
  builtIn = "Built-in",
  eval = "Eval",
  audio = "Audio",
  workflows = "Workflows",
}

export const HSTColors: Partial<Record<HST, string>> = {
  [HST.backend]: "from-primary/5",
  [HST.frontend]: "from-secondary/5",
  [HST.satellite]: "from-accent/5",
};

export const HSTColorOpts = Object.keys(HSTColors) as HST[];

export const HSTTooltips: Partial<Record<HST, string>> = {
  [HST.backend]: "Inference backend. Runs LLMs or other models.",
  [HST.frontend]:
    "Inference frontend, can serve as an interface for supported backends.",
  [HST.satellite]:
    "Satellite service, usually a utility or helper service that can utilise LLMs or be used by other services.",
  [HST.api]: "Service is oriented towards API workloads.",
  [HST.cli]: "Service has a CLI interface.",
  [HST.partial]: "Harbor only supports this service partially.",
  [HST.builtIn]: "Service is built-in to Harbor, developed by the Harbor team.",
  [HST.eval]: "Service is used for evaluation or benchmarking.",
  [HST.audio]: "Service is oriented towards working with audio.",
  [HST.workflows]: "Service provides visual workflow building functionality.",
};

export const TAG_ADORNMENTS: Partial<Record<HST, React.ReactNode>> = {
  [HST.partial]: (
    <span className="mr-1 opacity-40">
      <IconBandage />
    </span>
  ),
  [HST.builtIn]: (
    <span className="mr-1 opacity-40">
      <IconAward />
    </span>
  ),
  [HST.audio]: (
    <span className="mr-1 opacity-40">
      <IconAudioLines />
    </span>
  ),
};

export const ServiceTag = (
  { tag }: { tag: HarborService["tags"][number] },
) => {
  const maybeAdornment = TAG_ADORNMENTS[tag] ?? null;

  return (
    <span className="tooltip tooltip-bottom label-text" data-tip={HSTTooltips[tag]}>
      <span
        key={tag}
        className="badge bg-base-content/5 text-base-content/80 group-has-[input:checked]:badge-neutral"
      >
        {maybeAdornment}
        {tag}
      </span>
    </span>
  );
};

export const ServiceTags = (
  { service }: { service: HarborService },
) => {
  return (
    <div className="badges flex gap-2">
      {service.isDefault && (
        <span className="badge badge-primary">
          Default
        </span>
      )}
      {service.tags.map(
        (tag) => <ServiceTag key={tag} tag={tag} />,
      )}
    </div>
  );
};
