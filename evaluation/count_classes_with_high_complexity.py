import os
import numpy as np
import re
import sys
import json
import subprocess
import csv
import logging
import os


def get_d4j_subjects():
    d4j_subjects = []
    with open('d4j-fixed-version.csv', 'r') as file:
        reader = csv.reader(file)
        next(reader)

        for row in reader:
            # Append the first column value to the list
            d4j_subjects.append(row[0])
    return d4j_subjects


if __name__ == '__main__':
    output_file = 'data/high_complexity_classes.csv'
    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['project_name', 'class_name', 'max_cc']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        with open('data/testing_classes.csv', 'r') as file:
            reader = csv.reader(file)
            next(reader)

            for row in reader:
                # Append the first column value to the list
                project_name = row[0]
                class_name = row[1]
                try:
                    with open(os.path.join("defects4j-codefiles", f"{project_name}-codefiles.json"), 'r') as f:
                        data = json.load(f)
                except FileNotFoundError:
                    continue

                file_objects = data["src_test_exact_match"] + data["src_test_fuzz_match"] + data["src_without_tests"]
                for src_file in file_objects:
                    if src_file["src_name"] == class_name:
                        if "methods_under_test" in src_file.keys():
                            max_cc = 0
                            for key, methods in src_file["methods_under_test"].items():
                                for key, value in methods.items():
                                    if value[0] == value[1] == value[2]:
                                        if value[0] > max_cc:
                                            max_cc = value[0]

                            print(project_name, class_name, src_file["src_name"], max_cc)
                            writer.writerow({'project_name': project_name, 'class_name': class_name, 'max_cc': max_cc})
