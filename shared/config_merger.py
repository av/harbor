import os
import yaml
import argparse

def read_yaml(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def write_yaml(data, file_path):
    with open(file_path, 'w') as file:
        yaml.dump(data, file, default_flow_style=False)

def merge_yaml_files(directory, pattern, output_file):
    merged_data = {}

    for filename in os.listdir(directory):
        if filename.endswith(pattern):
            file_path = os.path.join(directory, filename)
            yaml_data = read_yaml(file_path)

            # Merge the data
            for key, value in yaml_data.items():
                if key in merged_data:
                    if isinstance(merged_data[key], dict) and isinstance(value, dict):
                        merged_data[key].update(value)
                    elif isinstance(merged_data[key], list) and isinstance(value, list):
                        merged_data[key].extend(value)
                    else:
                        merged_data[key] = value
                else:
                    merged_data[key] = value

    # Write the merged data to the output file
    write_yaml(merged_data, output_file)

def main():
    parser = argparse.ArgumentParser(description='Merge YAML files in a directory.')
    parser.add_argument('--pattern', default='.yaml', help='File pattern to match (default: .yaml)')
    parser.add_argument('--output', default='merged_output.yaml', help='Output file name (default: merged_output.yaml)')
    parser.add_argument('--directory', default='.', help='Directory to search for YAML files (default: current directory)')

    args = parser.parse_args()

    merge_yaml_files(args.directory, args.pattern, args.output)
    print(f"Merged YAML files matching '{args.pattern}' into '{args.output}'")

if __name__ == '__main__':
    main()