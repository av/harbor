import os
import yaml
import argparse
import re

def read_yaml(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def write_yaml(data, file_path):
    with open(file_path, 'w') as file:
        yaml.dump(data, file, default_flow_style=False)

def render_env_vars(value):
    if isinstance(value, str):
        pattern = r'\$\{([^}]+)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)'

        def replace_env_var(match):
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))

        return re.sub(pattern, replace_env_var, value)
    elif isinstance(value, list):
        return [render_env_vars(item) for item in value]
    elif isinstance(value, dict):
        return {k: render_env_vars(v) for k, v in value.items()}
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

def merge_yaml_files(directory, pattern, output_file):
    merged_data = {}

    for filename in sorted(os.listdir(directory)):
        if filename.endswith(pattern):
            file_path = os.path.join(directory, filename)
            yaml_data = read_yaml(file_path)

            # Render environment variables
            yaml_data = render_env_vars(yaml_data)

            # Merge the data
            merged_data = merge_dicts(merged_data, yaml_data)

    # Write the merged data to the output file
    write_yaml(merged_data, output_file)

def main():
    parser = argparse.ArgumentParser(description='Merge YAML files in a directory and render environment variables.')
    parser.add_argument('--pattern', default='.yaml', help='File pattern to match (default: .yaml)')
    parser.add_argument('--output', default='merged_output.yaml', help='Output file name (default: merged_output.yaml)')
    parser.add_argument('--directory', default='.', help='Directory to search for YAML files (default: current directory)')

    args = parser.parse_args()

    merge_yaml_files(args.directory, args.pattern, args.output)
    if os.environ.get('HARBOR_LOG_LEVEL', '').upper() == 'DEBUG':
        print(f"Merged YAML files matching '{args.pattern}' into '{args.output}' with environment variables rendered")

if __name__ == '__main__':
    main()