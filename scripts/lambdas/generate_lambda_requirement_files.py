import yaml
import os

from scripts.lambdas import generate_lambda_requirements


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
