import yaml
import ast
import os
import sys
from stdlib_list import stdlib_list


def get_python_interpreter_info():
    interpreter_path = sys.executable
    venv_root = os.path.dirname(os.path.dirname(interpreter_path))
    pyvenv_cfg_path = os.path.join(venv_root, "pyvenv.cfg")

    def get_version_from_cfg(cfg_path):
        if not os.path.isfile(cfg_path):
            return None
        with open(cfg_path, "r") as f:
            for line in f:
                if line.strip().startswith("version"):
                    return line.strip().split("=")[-1].strip()
        return None

    def truncate_version(version_string):
        parts = version_string.strip().split(".")
        return ".".join(parts[:2])  # only major.minor

    version = get_version_from_cfg(pyvenv_cfg_path)
    if not version:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
    else:
        version = truncate_version(version)

    print(f"🧪 Python interpreter: {interpreter_path}")
    print(f"🐍 Python version: {version}")

    return version


def resolve_local_module_path(module_name, project_root):
    parts = module_name.split(".")
    potential_file = os.path.join(project_root, *parts) + ".py"
    potential_init = os.path.join(project_root, *parts, "__init__.py")
    if os.path.isfile(potential_file):
        return potential_file
    elif os.path.isfile(potential_init):
        return potential_init
    return None


def extract_all_imports(entry_file, project_root, stdlib_modules):
    visited_files = set()
    all_imports = set()

    def visit_file(file_path):
        if not os.path.isfile(file_path) or file_path in visited_files:
            return
        visited_files.add(file_path)

        with open(file_path, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=file_path)
            except SyntaxError:
                return

        for node in tree.body:  # ONLY top-level imports
            mod = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    all_imports.add(mod)
                    local_path = resolve_local_module_path(alias.name, project_root)
                    if local_path:
                        visit_file(local_path)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mod = node.module.split(".")[0]
                    all_imports.add(mod)
                    local_path = resolve_local_module_path(node.module, project_root)
                    if local_path:
                        visit_file(local_path)

    visit_file(entry_file)
    return all_imports


def get_project_modules(project_root):
    return {
        name.split(".")[0]
        for name in os.listdir(project_root)
        if name.endswith(".py") or os.path.isdir(os.path.join(project_root, name))
    }


def match_with_reference(external_deps, reference_file):
    with open(reference_file, "r") as ref:
        reference_lines = ref.readlines()

    matched_lines = []
    for mod in external_deps:
        for line in reference_lines:
            if mod.lower() in line.lower():
                matched_lines.append(line.strip())
    return sorted(set(matched_lines))


def write_requirements(output_folder, matched_lines):
    os.makedirs(output_folder, exist_ok=True)
    output_file_path = os.path.join(output_folder, "requirements.txt")
    with open(output_file_path, "w") as out:
        out.write("\n".join(matched_lines) + "\n")
    print(f"✅ requirements.txt written to: {output_file_path}")


def generate_lambda_requirements(
    entry_file, project_root, reference_file, output_folder
):
    python_version = get_python_interpreter_info()
    stdlib_modules = set(stdlib_list(python_version))
    all_imports = extract_all_imports(entry_file, project_root, stdlib_modules)
    project_modules = get_project_modules(project_root)

    external_deps = sorted(
        {
            mod
            for mod in all_imports
            if mod not in stdlib_modules and mod not in project_modules
        }
    )

    print(f"📦 External dependencies identified: {external_deps}")

    matched_lines = match_with_reference(external_deps, reference_file)
    write_requirements(output_folder, matched_lines)


# Allow PyYAML to load CloudFormation tags like !Ref
class CFNYamlLoader(yaml.SafeLoader):
    pass


def construct_unknown_tag(loader, tag_suffix, node):
    return loader.construct_scalar(node)


# Register unknown tag handler for all CloudFormation-style tags
CFNYamlLoader.add_multi_constructor("!", construct_unknown_tag)


template_path = (
    "/Users/bhaskar/Desktop/other/job-hunt/utilities/aws/serverless/template.yaml"
)
with open(template_path, "r") as f:
    data = yaml.load(f, Loader=CFNYamlLoader)

resources = data.get("Resources", {})
lambda_info = []

for name, resource in resources.items():
    if resource.get("Type") == "AWS::Serverless::Function":
        properties = resource.get("Properties", {})

        lambda_folder = properties.get("CodeUri")
        handler_file = f"{properties.get('Handler').split('.')[0]}.py"

        generate_lambda_requirements(
            entry_file=os.path.join(lambda_folder, handler_file),
            project_root="/Users/bhaskar/Desktop/other/job-hunt",
            reference_file="/Users/bhaskar/Desktop/other/job-hunt/requirements.txt",
            output_folder=lambda_folder,
        )
