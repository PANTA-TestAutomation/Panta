from bs4 import BeautifulSoup
import json
import csv
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
print(ROOT)
def read_html_file(file_name, file_path):
    with open(f"{file_path}/{file_name}", 'r', encoding='utf-8') as file:
        return file.read()


def append_to_csv_file(filename, row):
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(row)


def create_csv_file(filename, header):
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(header)


def count_method_under_tests(m_dict):
    count = 0
    for key in m_dict:
        if key == "to_be_determined":
            continue
        count += len(m_dict[key])
    return count


def get_d4j_subject_classes():
    d4j_subjects = {}
    with open('data/class_list.csv', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            # Append the first column value to the list
            project_name = row[0]
            class_name = row[1]
            max_cc = row[2]
            if d4j_subjects.get(project_name):
                d4j_subjects.get(project_name)[class_name] = max_cc
            else:
                d4j_subjects[project_name] = {class_name: max_cc}
    return d4j_subjects

def parse_line_branch_coverage(class_name: str, prompt_type: str, file_path, model="llama3"):
    f"""
    parse ../result-files/{prompt_type}_{model}/{class_name}_{prompt_type}_test_results.html to identify line/branch coverage
    :param file_path: 
    :param class_name
    :param prompt_type
    :return:
    """
    try:
        coverage = []
        html_file = f"{class_name}_{prompt_type}_test_results.html"

        html_content = read_html_file(html_file, file_path)
        soup = BeautifulSoup(html_content, 'html.parser')
        # Find the table in the HTML content
        table = soup.find('table')

        if not table:
            raise ValueError("No table found in the provided HTML file.")

        # Iterate over the rows of the table (skip the header row)
        rows = table.find_all('tr')[1:]  # Skip the header row
        row_id = 0
        for row in rows:
            columns = row.find_all('td')
            row_id += 1
            if len(columns) < 6:
                continue  # Skip rows that do not have enough columns

            # Extract details
            status = columns[0].text.strip()
            label = columns[1].text.strip()
            reason = columns[2].text.strip()
            line_coverage = float(columns[4].text.strip())
            branch_coverage = float(columns[5].text.strip())

            # Store coverage data in the dictionary
            coverage.append({
                "label": label,
                "status": status,
                "reason": reason,
                "line_coverage": line_coverage,
                "branch_coverage": branch_coverage
            })
        return coverage
    except Exception as e:
        print(e)
        return []



def get_coverage_for_first_iteration(parsed_coverage_list):
    if not parsed_coverage_list:
        return None, None
    branch_cov_g_0 = [item["branch_coverage"] for item in parsed_coverage_list if item["label"] == "g_0"]
    line_cov_g_0 = [item["line_coverage"] for item in parsed_coverage_list if item["label"] == "g_0"]
    line_no_fixing = line_cov_g_0[-1]

    branch_no_fixing = branch_cov_g_0[-1]

    return line_no_fixing, branch_no_fixing,


def append_result_to_csv(project, class_name, max_cc, category, m_num):
    control_prompt_type = "control"
    control_path = f"{ROOT}/result-files/control_llama3-3"
    control_coverage_list = parse_line_branch_coverage(class_name, control_prompt_type, control_path)

    if control_coverage_list:
        llama_line, llama_branch = control_coverage_list[-1]["line_coverage"], control_coverage_list[-1][
            "branch_coverage"]

    else:
        llama_line, llama_branch = None, None

    control_path = f"{ROOT}/result-files/control_gpt-4o-mini"
    control_coverage_list = parse_line_branch_coverage(class_name, control_prompt_type, control_path)

    if control_coverage_list:
        gpt_line, gpt_branch = control_coverage_list[-1]["line_coverage"], control_coverage_list[-1][
            "branch_coverage"]

    else:
        gpt_line, gpt_branch = None, None

    control_path = f"{ROOT}/result-files/control_claude3-5"
    control_coverage_list = parse_line_branch_coverage(class_name, control_prompt_type, control_path)

    if control_coverage_list:
        claude_line, claude_branch = control_coverage_list[-1]["line_coverage"], control_coverage_list[-1][
            "branch_coverage"]

    else:
        claude_line, claude_branch = None, None

    control_path = f"{ROOT}/result-files/control_mistral-large"
    control_coverage_list = parse_line_branch_coverage(class_name, control_prompt_type, control_path)

    if control_coverage_list:
        mistral_line, mistral_branch = control_coverage_list[-1]["line_coverage"], control_coverage_list[-1][
            "branch_coverage"]

    else:
        mistral_line, mistral_branch = None, None

    row = [project, class_name, max_cc, category, m_num, llama_line, llama_branch, gpt_line, gpt_branch,
           claude_line, claude_branch, mistral_line, mistral_branch]
    append_to_csv_file(subjects_file, row)


if __name__ == '__main__':
    subjects_file = "coverage_statistics_models.csv"
    header = ["project", 'class', "complexity", "category", "methods",
              "llama_line", "llama_branch", "gpt_line", "gpt_branch", "claude_line", "claude_branch",
              "mistral_line", "mistral_branch"]
    create_csv_file(subjects_file, header)
    if __name__ == '__main__':
        defects4j_subjects = ["JacksonXml-5f", "Csv-16f", "Collections-28f", "Gson-16f", "Cli-40f", "JacksonCore-26f",
                              "JxPath-22f", "Jsoup-93f", "Codec-18f", "Compress-47f", "JacksonDatabind-112f",
                              "Time-13f", "Lang-4f", "Math-2f"]
        defects4j_subject_classes = get_d4j_subject_classes()
        for p_name in defects4j_subjects:
            print(p_name)
            class_subjects = defects4j_subject_classes[p_name]
            with open(os.path.join("defects4j-codefiles", f"{p_name}-codefiles.json"), 'r') as f:
                data = json.load(f)
            count_1 = 0
            count_2 = 0
            categories = ["src_test_exact_match", "src_test_fuzz_match", "src_without_tests"]
            for index, categ in enumerate(categories):
                for src_file in data[categ]:
                    keyword = ""
                    if "methods_under_test" in src_file.keys():
                        # if "abstract" in src_file["class_declaration"]:
                        #     keyword += "a"
                        if "extends" in src_file["class_declaration"]:
                            keyword += "e"
                        if src_file["src_name"] not in class_subjects:
                            continue
                        max_cc = class_subjects[src_file["src_name"]]
                        method_num = count_method_under_tests(src_file["methods_under_test"])
                        append_result_to_csv(p_name, src_file["src_name"], max_cc, keyword, method_num)
