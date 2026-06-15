import json
import subprocess
import csv
import os
import configparser
import sys
import argparse
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]

def extract_config_data(src_file_obj, project_name, model):
    if project_name == "Gson-16f":
        project_dir = "defects4j-subjects-notests/" + project_name + "/gson"
    else:
        project_dir = "defects4j-subjects-notests/" + project_name
    src_path = src_file_obj["src_path"].replace("defects4j-subjects", "defects4j-subjects-notests")
    src_path = src_path.lstrip("../")
    # test_path = src_file_obj["test_path"].replace("defects4j-subjects", "defects4j-subjects-notests")
    file_name = os.path.basename(src_path)
    dir_name = os.path.dirname(src_path)
    if project_name == "JxPath-22f":
        test_dir = dir_name.replace("src/java", "src/test")
    else:
        test_dir = dir_name.replace("src/main/java", "src/test/java")

    test_name = file_name.replace(f"{src_file_obj['src_name']}.java", f"{src_file_obj['src_name']}Test.java")
    test_path = os.path.join(test_dir, test_name)

    if os.path.exists(test_path):
        os.remove(test_path)
    test_file_name = os.path.splitext(test_name)[0]
    code_coverage_report_path = project_dir + "/target/jacoco/jacoco.csv"
    test_execution_command = f"mvn clean package -Dtest={test_file_name}"
    test_code_command_dir = project_dir

    junit_version = '4'

    config_data = {
        'default': {
            'project_directory': project_dir,
            'source_code_file': src_path,
            'test_code_file': test_path,
            'code_coverage_report_path': code_coverage_report_path,
            'test_execution_command': test_execution_command,
            'test_code_command_dir': test_code_command_dir,
            'junit_version': junit_version,
            'model': model,
            'run_symprompt': 'true'
        }
    }
    return config_data


def fill_config(config_data, filename="config.ini"):
    # Initialize the ConfigParser
    config = configparser.ConfigParser()

    # Load existing configuration if the file exists
    config.read(filename)

    # Update config with provided data
    for section, settings in config_data.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in settings.items():
            config.set(section, key, value)

    # Write the config to the file
    with open(filename, 'w') as configfile:
        config.write(configfile)
    print(f"Configuration written to {filename}")


def read_html_file(file_name, file_path):
    with open(f"{file_path}/{file_name}", 'r', encoding='utf-8') as file:
        return file.read()


def parse_line_branch_coverage(class_name: str, prompt_type: str, file_path, model="llama3"):
    f"""
    parse ../result-files/{prompt_type}_{model}/{class_name}_{prompt_type}_test_results.html to identify line/branch coverage
    :param file_path: 
    :param class_name
    :param prompt_type
    :return:
    """
    try:
        html_file = f"{class_name}_{prompt_type}_test_results.html"
        html_content = read_html_file(html_file, file_path)
        soup = BeautifulSoup(html_content, 'html.parser')
        # Find the table in the HTML content
        table = soup.find('table')

        if not table:
            raise ValueError("No table found in the provided HTML file.")

        # Iterate over the rows of the table (skip the header row)
        rows = table.find_all('tr')[1:]  # Skip the header row
        last_row = rows[-1]
        columns = last_row.find_all('td')
        line_coverage = float(columns[4].text.strip())
        branch_coverage = float(columns[5].text.strip())
        return True
    except Exception as e:
        #print(e)
        return False


def get_d4j_subject_classes(class_list="class_list.csv"):
    d4j_subjects = {}
    with open(f'data/{class_list}', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            project_name = row[0]
            class_name = row[1]
            max_cc = row[2]
            if d4j_subjects.get(project_name):
                d4j_subjects.get(project_name)[class_name] = max_cc
            else:
                d4j_subjects[project_name] = {class_name: max_cc}
    return d4j_subjects


def fill_config_and_execute(src_f, proj_name, model):
    config_data = extract_config_data(src_f, proj_name, model)
    fill_config(config_data, filename=f"{ROOT}/src/panta/config.ini")
    cmd = ["python", "-m", "panta.main"]
    process = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        print(line, end='')

    exit_code = process.wait()
    print("Exit Code:", exit_code)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run SymPrompt evaluation")
    parser.add_argument("prompt", help="The prompt to use")
    parser.add_argument("model", help="The model to use")
    parser.add_argument(
        "--class-list",
        default="class_list.csv",
        help="Optional list of classes (defaults to class_list.csv)"
    )

    args = parser.parse_args()
    print(args.class_list)

    defects4j_subject_classes = get_d4j_subject_classes(class_list=args.class_list)
    result_path = f"{ROOT}/result-files/{args.prompt}_{args.model}"
    defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                          "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                          "Time-13f", "Lang-4f", "Math-2f"]
    
    for p_name in defects4j_subjects:
        if p_name not in defects4j_subject_classes.keys():
            continue
            
        with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
            data = json.load(f)

        file_objects = data["src_test_exact_match"] + data["src_test_fuzz_match"] + data["src_without_tests"]
        class_subjects = defects4j_subject_classes[p_name]
        for src_file in file_objects:
            html_file = f"{result_path}/{src_file['src_name']}_{args.prompt}_test_results.html"
            if src_file["src_name"] in class_subjects.keys():
                max_cc = class_subjects[src_file["src_name"]]
                if not os.path.exists(html_file):
                    print("execute", src_file["src_name"], max_cc)
                    fill_config_and_execute(src_file, p_name, args.model)
