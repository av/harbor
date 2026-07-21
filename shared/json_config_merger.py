import os
import json
import argparse
import re

def read_json(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)

def write_json(data, file_path):
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=2)

def render_env_vars(value):
    def is_section_enabled(section):
        pattern = r'\$\{\.\.\.([^}]+)\}|\$\{([^}]+)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)'
        env_vars = re.findall(pattern, json.dumps(section))
        if not env_vars:
            return True  # Always include sections without env vars
        return any(os.environ.get(var[0] or var[1] or var[2]) for var in env_vars)

    if isinstance(value, str):
        if not value:  # Return empty string as is
            return value
        pattern = r'\$\{\.\.\.([^}]+)\}|\$\{([^}]+)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)'

        def replace_env_var(match):
            spread_var = match.group(1)
            normal_var = match.group(2) or match.group(3)

            if spread_var:
                env_value = os.environ.get(spread_var, '')
                return [v.strip() for v in env_value.split(';') if v.strip()]
            else:
                return os.environ.get(normal_var, match.group(0))

        parts = re.split(pattern, value)
        result = []
        for i, part in enumerate(parts):
            if i % 4 == 0:  # Normal text
                if part:
                    result.append(part)
            elif i % 4 == 1:  # Spread variable
                if part:
                    env_value = os.environ.get(part, '')
                    result.extend([v.strip() for v in env_value.split(';') if v.strip()])
            else:  # Normal variable
                if part:
                    env_value = os.environ.get(part, f'${{{part}}}')
                    if env_value:
                        result.append(env_value)

        if not result:  # Return empty string if result is empty
            return value
        if len(result) == 1 and isinstance(result[0], str):
            return result[0]
        return result
    elif isinstance(value, list):
        flattened = []
        for item in value:
            rendered_item = render_env_vars(item)
            if isinstance(rendered_item, list):
                flattened.extend(rendered_item)
            else:
                flattened.append(rendered_item)
        return flattened
    elif isinstance(value, dict):
        rendered_dict = {}
        for k, v in value.items():
            if isinstance(v, dict) and not is_section_enabled(v):
                continue
            rendered_value = render_env_vars(v)
            rendered_dict[k] = rendered_value
        return rendered_dict
    else:
        return value

def merge_dicts(dict1, dict2):
    """
    Recursively merge two dictionaries.
    Lists are combined, dictionaries are recursively merged, other values are overwritten.
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_dicts(result[key], value)
            elif isinstance(result[key], list) and isinstance(value, list):
                result[key].extend(value)
            else:
                result[key] = value
        else:
            result[key] = value
    return result

# Open WebUI config keys whose registered value is a dict — flattening must
# stop at these paths so the whole object lands under a single config row.
DICT_VALUE_KEYS = {
    "models.default_params",
    "models.default_metadata",
    "openai.api_configs",
    "ollama.api_configs",
    "user.permissions",
    "audio.tts.openai.params",
    "image_generation.openai.params",
    "image_generation.automatic1111.api_params",
    "rag.mineru_params",
    "rag.docling_params",
    "rag.external_document_loader_headers",
    "web.search.linkup_search_params",
    "rag.web.search.linkup_search_params",
}

# Legacy Harbor config keys -> current Open WebUI registered key paths.
FLAT_KEY_ALIASES = {
    "openai.enabled": "openai.enable",
    "ollama.enabled": "ollama.enable",
}

def flatten_config(data, prefix=""):
    """
    Flatten nested config into dot-path keys, e.g.
    {"audio": {"tts": {"engine": "openai"}}} -> {"audio.tts.engine": "openai"}.
    Newer Open WebUI imports data/config.json as flat per-key config rows,
    so nested sections are silently ignored unless flattened.
    """
    flat = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value and path not in DICT_VALUE_KEYS:
            flat.update(flatten_config(value, f"{path}."))
        else:
            flat[FLAT_KEY_ALIASES.get(path, path)] = value
    return flat

def merge_json_files(directory, pattern, output_file, flatten=False):
    merged_data = {}

    for filename in sorted(os.listdir(directory)):
        if filename.endswith(pattern):
            file_path = os.path.join(directory, filename)
            json_data = read_json(file_path)

            # Render environment variables
            json_data = render_env_vars(json_data)

            # Merge the data
            merged_data = merge_dicts(merged_data, json_data)

    if flatten:
        merged_data = flatten_config(merged_data)

    # Write the merged data to the output file
    write_json(merged_data, output_file)

def main():
    parser = argparse.ArgumentParser(description='Merge JSON files in a directory and render environment variables.')
    parser.add_argument('--pattern', default='.json', help='File pattern to match (default: .json)')
    parser.add_argument('--output', default='merged_output.json', help='Output file name (default: merged_output.json)')
    parser.add_argument('--directory', default='.', help='Directory to search for JSON files (default: current directory)')
    parser.add_argument('--flatten', action='store_true', help='Flatten merged config into dot-path keys (Open WebUI per-key config format)')

    args = parser.parse_args()

    merge_json_files(args.directory, args.pattern, args.output, flatten=args.flatten)
    print(f"Merged JSON files matching '{args.pattern}' into '{args.output}' with environment variables rendered")

if __name__ == '__main__':
    main()