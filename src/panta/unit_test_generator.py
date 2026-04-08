import json
import os
import re

from .command_executor import CommandExecutor
from .coverage.jacoco_coverage import JacocoCoverage
from .coverage.pycov_coverage import PycovCoverage
from .error_message_parser import extract_error_message, extract_compilation_error_message_java
from .file_preprocessor import FilePreprocessor
from .panta_logger import pantaLogger
from .model_invocation.llm_invocation import LLMInvocation
from .prompt_builder import PromptBuilder
from .utils import get_code_language
from .yaml_parser_utils import load_yaml
from .cfg.src.comex.codeviews.combined_graph.combined_driver import line_number_to_node_id_mapping
from .cfg.src.comex.codeviews.CFG.CFG_driver import CFGDriver
from .utils import read_file


def count_leading_spaces(text):
    match = re.match(r'^ +', text)
    if match:
        return len(match.group(0))
    return 0


def failed_test_to_string(failed_test: dict):
    failed_test_str = ""
    failed_test_dict = failed_test.get("code", {})
    error_message = failed_test.get("error_message", "")
    if failed_test_dict:
        failed_test_code = failed_test_dict.get("test_code", "").rstrip()
        failed_test_imports = (failed_test_dict.get("new_imports_code", "") or "").strip()
        failed_test_name = failed_test_dict.get("test_name", "").rstrip()
        failed_test_str += f"=========The failed test case is : {failed_test_name}=======\n"
        failed_test_str += f"{failed_test_code}\n"
        failed_test_str += f"additional imports: {failed_test_imports}\n"

        if error_message:
            failed_test_str += f"Failed with error message:\n{error_message}\n\n"
        else:
            failed_test_str += "\n\n"
    return failed_test_str


class UnitTestGenerator:
    def __init__(self, project_dir: str,
                 source_code_file: str,
                 test_code_file: str,
                 code_coverage_report_path: str,
                 test_execution_command: str,
                 llm_model: str,
                 test_code_command_dir: str = os.getcwd(),
                 test_dependencies: str = "",
                 included_files: list = None,
                 coverage_type="jacoco",
                 target_coverage: int = 100,
                 prompt_type: str = "baseline",
                 additional_instructions: str = ""):

        self.relevant_line_number_to_insert_tests_after = None
        self.relevant_line_number_to_insert_imports_after = None
        self.relevant_line_number_to_insert_tests_before = None
        self.test_headers_indentation = None
        self.lines_missed = None
        self.branch_missed = None
        self.current_coverage = None
        self.code_coverage_report = None
        self.project_dir = project_dir
        self.source_code_file = source_code_file
        self.test_code_file = test_code_file
        self.code_coverage_report_path = code_coverage_report_path
        self.test_execution_command = test_execution_command
        self.test_code_command_dir = test_code_command_dir
        self.test_dependencies = test_dependencies
        self.included_files = self.get_included_files(included_files)
        self.coverage_type = coverage_type
        self.target_coverage = target_coverage
        self.additional_instructions = additional_instructions
        self.language = get_code_language(source_code_file)

        self.llm_invoker = LLMInvocation(model=llm_model)

        self.logger = pantaLogger.initialize_logger(__name__)

        self.preprocessor = FilePreprocessor(self.test_code_file)
        self.failed_test_runs = []
        self.coverage_invalid_tests = []
        self.run_coverage()
        self.prompt_type = prompt_type
        self.path_history = {}
        # self.prompt = self.build_prompt(self.prompt_type)
        self.prompt = ""

    def run_coverage(self):
        """
        run the build/test command and get the baseline coverage
        """
        self.logger.info(f'generate baseline coverage report: "{self.test_execution_command}"')
        try:
            stdout, stderr, exit_code, time_of_test_execution_command, command_duration = CommandExecutor.run_command(
                command=self.test_execution_command, cwd=self.test_code_command_dir
            )

            if exit_code != 0:
                raise RuntimeError(
                    f'Fatal: Error running test command. '
                    f'make sure this build command is correct: "{self.test_execution_command}"\n'
                    f'Exit code: {exit_code}'
                    f'\nStdout: {stdout}'
                    f'\nStderr: {stderr}'
                )

            # Instantiate Coverage and process the coverage report
            if self.coverage_type == "jacoco":
                coverage_processor = JacocoCoverage(
                    project_dir=self.project_dir,
                    file_path=self.code_coverage_report_path,
                    src_file_path=self.source_code_file)
            elif self.coverage_type == "pycov":
                coverage_processor = PycovCoverage(
                    file_path=self.code_coverage_report_path,
                    src_file_path=self.source_code_file)
            else:
                raise ValueError(f"Unsupported coverage type: {self.coverage_type}")

            # Use the process_coverage_report method of Coverage, passing in the time the test command was executed
            try:
                self.lines_missed, self.branch_missed, line_percentage, branch_percentage = (
                    coverage_processor.process_coverage_report(
                        time_of_test_execution_command=time_of_test_execution_command
                    )
                )

                # Process the extracted coverage metrics
                self.current_coverage = (line_percentage, branch_percentage)
                self.code_coverage_report = f"Lines missed: {self.lines_missed}\n" \
                                            f"Branches missed: {self.branch_missed}\n" \
                                            f"Line coverage: {round(line_percentage * 100, 2)}%\n" \
                                            f"Branch coverage: {round(branch_percentage * 100, 2)}%"
            except AssertionError as error:
                self.logger.error(f"Error in coverage processing: {error}")
                raise
            except (ValueError, NotImplementedError) as e:
                self.logger.warning(f"Error parsing coverage report: {e}")
                with open(self.code_coverage_report_path, "r") as f:
                    self.code_coverage_report = f.read()
        except Exception as e:
            self.logger.error(str(e))
            raise

    @staticmethod
    def get_included_files(included_files):
        if included_files:
            included_files_content = []
            file_names = []
            for file_path in included_files:
                try:
                    with open(file_path, "r") as file:
                        included_files_content.append(file.read())
                        file_names.append(file_path)
                except IOError as e:
                    print(f"Error reading file {file_path}: {str(e)}")

            out_str = ""
            if included_files_content:
                for i, content in enumerate(included_files_content):
                    out_str += f"file_path: `{file_names[i]}`\ncontent:\n```\n{content}\n```\n"

            return out_str.strip()
        return ""

    def build_prompt(self, prompt_type, pick_two_paths=True) -> dict:
        """
        Returns:
            str: prompt that will be used for generating new tests
        """

        failed_test_runs_value = ""
        try:
            # Check for existence of failed tests:
            for failed_test in self.failed_test_runs:
                failed_test_str = failed_test_to_string(failed_test)
                failed_test_runs_value += failed_test_str
        except Exception as e:
            self.logger.error(f"Error processing failed test runs: {e}")
        self.failed_test_runs = []

        no_coverage_increase_tests_value = ""
        # if self.coverage_invalid_tests:
        #     try:
        #         for test in self.coverage_invalid_tests:
        #             test_dict = test.get("code", {})
        #             if not test_dict:
        #                 continue
        #             test_code = test_dict.get("test_code", "").rstrip()
        #             test_imports = (test_dict.get("new_imports_code", "") or "").strip()
        #             test_name = test_dict.get("test_name", "").rstrip()
        #             no_coverage_increase_tests_value += f"======== No coverage improvement for test {test_name} ========\n"
        #             no_coverage_increase_tests_value += f"additional imports: {test_imports}\n"
        #             no_coverage_increase_tests_value += f"{test_code}\n"
        #             no_coverage_increase_tests_value += f"Code coverage did not increase for the test {test_name}, " \
        #                                                 f"avoid generating the same test again\n\n"
        #
        #     except Exception as e:
        #         self.logger.error(f"Error processing failed test runs: {e}")
        #
        # self.coverage_invalid_tests = []

        self.prompt_builder = PromptBuilder(
            project_dir=self.project_dir,
            source_code_file=self.source_code_file,
            test_code_file=self.test_code_file,
            code_coverage_report=self.code_coverage_report,
            included_files=self.included_files,
            additional_instructions=self.additional_instructions,
            failed_test_runs=failed_test_runs_value,
            coverage_invalid_tests=no_coverage_increase_tests_value,
            language=self.language,
            lines_missed=self.lines_missed,
            branch_missed=self.branch_missed,
            path_history=self.path_history,
            test_dependencies=self.test_dependencies
        )
        if prompt_type == "control":
            prompt = self.prompt_builder.build_prompt_cfa_guided(pick_two_paths)
            self.path_history = self.prompt_builder.get_current_path_history()
            return prompt
        elif prompt_type == "coverage":
            return self.prompt_builder.build_prompt(coverage_enabled=True)
        else:
            return self.prompt_builder.build_prompt(coverage_enabled=False)

    def initial_test_suite_analysis(self):
        """
        Simple implementation for initial test suite analysis.
        We can move to an approach using AST or string parsing, instead of just using LLM for everything.
        Specifically, when we can use AST to extract the test headers indentation and the relevant line number to insert new tests.
        :return:
        """
        try:
            test_headers_indentation = None
            allowed_attempts = 3
            counter_attempts = 0
            while test_headers_indentation is None and counter_attempts < allowed_attempts:
                prompt_headers_indentation = (
                    self.prompt_builder.build_prompt_custom(
                        file="test_headers_indentation_prompt"
                    )
                )
                response, prompt_token_count, response_token_count, cost = (
                    self.llm_invoker.call_model(prompt=prompt_headers_indentation)
                )
                tests_dict = load_yaml(response)
                test_headers_indentation = tests_dict.get(
                    "test_headers_indentation", None
                )
                counter_attempts += 1

            if test_headers_indentation is None:
                raise Exception("Failed to analyze the test headers indentation")

            relevant_line_number_to_insert_tests_after = None
            relevant_line_number_to_insert_imports_after = None
            allowed_attempts = 3
            counter_attempts = 0
            while not relevant_line_number_to_insert_tests_after and counter_attempts < allowed_attempts:
                prompt_test_insert_line = (
                    self.prompt_builder.build_prompt_custom(
                        file="analyze_suite_test_insert_line"
                    )
                )
                response, prompt_token_count, response_token_count, cost = (
                    self.llm_invoker.call_model(prompt=prompt_test_insert_line)
                )
                tests_dict = load_yaml(response)
                relevant_line_number_to_insert_tests_after = tests_dict.get(
                    "relevant_line_number_to_insert_tests_after", None
                )
                relevant_line_number_to_insert_imports_after = tests_dict.get(
                    "relevant_line_number_to_insert_imports_after", None
                )
                counter_attempts += 1

            if not relevant_line_number_to_insert_tests_after:
                raise Exception(
                    "Failed to analyze the relevant line number to insert new tests"
                )

            self.test_headers_indentation = test_headers_indentation
            self.relevant_line_number_to_insert_tests_after = relevant_line_number_to_insert_tests_after
            self.relevant_line_number_to_insert_imports_after = relevant_line_number_to_insert_imports_after
        except Exception as e:
            self.logger.error(f"Error during initial test suite analysis: {e}")
            raise Exception("Error during initial test suite analysis")

    def initial_test_suite_analysis_AST(self):
        """
        Specifically, when we can use AST to extract the test headers indentation
        and the relevant line number to insert new tests.

        In the case, each test class has at least one existing test method.
        :return:
        """

        test_code = read_file(self.test_code_file)
        cfg_driver = CFGDriver(self.language, test_code, {"test_code": True})
        _, node_id_to_line_numbers_mapping = line_number_to_node_id_mapping(test_code, cfg_driver.CFG_nodes)
        last_import_id = cfg_driver.file_obj["imports"][-1]["id"]
        last_line_for_imports = node_id_to_line_numbers_mapping[last_import_id][-1]

        class_obj = cfg_driver.file_obj["class_objects"][0]
        class_declaration_id = class_obj["class_declaration"]["id"]
        class_declaration_start_line = node_id_to_line_numbers_mapping[class_declaration_id][0]

        last_method_declaration = class_obj["methods_under_test"][-1]
        last_method_start_id = last_method_declaration["method_declaration"]["id"]
        last_method_start_line = node_id_to_line_numbers_mapping[last_method_start_id][0]
        test_code_lines = test_code.split('\n')
        method_line_str = test_code_lines[last_method_start_line - 1]
        indents = count_leading_spaces(method_line_str)

        self.test_headers_indentation = indents
        self.relevant_line_number_to_insert_tests_before = last_method_start_line
        self.relevant_line_number_to_insert_imports_after = last_line_for_imports

    def generate_tests(self, g_label, max_tokens=4096, pick_two_paths=True):
        self.prompt = self.build_prompt(self.prompt_type, pick_two_paths)
        # self.logger.info(f"{g_label}: {self.path_history}")
        tests_dict, token_count, cost = self.generate_test_by_prompt_llm(self.prompt, max_tokens)
        return tests_dict, token_count, cost

    def generate_init_tests(self, prompt_type='baseline', max_tokens=4096):
        prompt = self.build_prompt(prompt_type)
        tests_dict, token_count, cost = self.generate_test_by_prompt_llm(prompt, max_tokens)
        return tests_dict, token_count, cost

    def generate_test_by_prompt_llm(self, prompt, max_tokens=4096):
        response, prompt_token_count, response_token_count, cost = (
            self.llm_invoker.call_model(prompt=prompt,
                                        max_tokens=max_tokens))
        self.logger.info(f"Total token count for LLM {self.llm_invoker.model}: "
                         f"{prompt_token_count + response_token_count}")
        token_count = prompt_token_count + response_token_count
        try:
            tests_dict = load_yaml(response, keys_fix_yaml=["test_code",
                                                            "test_name",
                                                            "test_behavior"], )
            if tests_dict is None:
                return {}
        except Exception as e:
            self.logger.error(f"Error during test generation: {e}")
            fail_details = {
                "status": "FAIL",
                "reason": f"Parsing error: {e}",
                "exit_code": None,  # No exit code as it's a parsing issue
                "stderr": str(e),
                "stdout": "",  # No output expected from a parsing error
                "test": response,  # Use the response that led to the error
            }
            # self.failed_test_runs.append(fail_details)
            tests_dict = []

        return tests_dict, token_count, cost

    def validate_test(self, generated_test: dict):
        # Try to add the generated test to the relevant section in the original test file
        with open(self.test_code_file, "r") as test_file:
            original_content = test_file.read()  # Store original content
        try:
            processed_test, relevant_line_number_to_insert_imports_after, \
            relevant_line_number_to_insert_tests_before = self.add_new_test_to_test_file(generated_test, original_content)
            if processed_test:
                with open(self.test_code_file, "w") as test_file:
                    test_file.write(processed_test)
                self.logger.info(f"Test added to the test file: {self.test_code_file}")
                test_name = generated_test.get("test_name")
                # if test_name:
                #     # Now try to run the test so that we can check if the newly added test is valid
                #     self.logger.info(f'Run test with the command: "{self.test_execution_command}#{test_name}"')
                #     stdout, stderr, exit_code, time_of_command, command_duration = CommandExecutor.run_command(
                #         command=f"{self.test_execution_command}#{test_name}", cwd=self.test_code_command_dir, timeout=10
                #     )
                # else:
                # Now try to run the test so that we can check if the newly added test is valid
                self.logger.info(f'Run test with the command: "{self.test_execution_command}"')
                stdout, stderr, exit_code, time_of_command, command_duration = CommandExecutor.run_command(
                    command=self.test_execution_command, cwd=self.test_code_command_dir, timeout=60
                )

                # Now we need to check if we were able to run the test successfully or not
                if exit_code != 0:
                    # As the test failed, we go back to the test file with the original content
                    with open(self.test_code_file, "w") as test_file:
                        test_file.write(original_content)
                    if "COMPILATION ERROR" in stdout or "Compilation failed" in stdout:
                        self.logger.info(f"Test generated with compilation error.")
                        error_message = extract_compilation_error_message_java(stdout)
                        failure_details = {
                            "status": "FAIL",
                            "reason": "Compilation failure",
                            "exit_code": exit_code,
                            "stderr": stderr,
                            "stdout": error_message,
                            "test": generated_test,
                            "line_coverage": round(self.current_coverage[0] * 100, 2),
                            "branch_coverage": round(self.current_coverage[1] * 100, 2)
                        }
                        self.failed_test_runs.append({
                            "code": generated_test,
                            "error_message": error_message
                        })
                    elif "Timeout" in stdout:
                        self.logger.info(f"Test generated failed due to timeout.")
                        failure_details = {
                            "status": "FAIL",
                            "reason": "Timeout",
                            "exit_code": exit_code,
                            "stderr": stderr,
                            "stdout": "Timeout",
                            "test": generated_test,
                            "line_coverage": round(self.current_coverage[0] * 100, 2),
                            "branch_coverage": round(self.current_coverage[1] * 100, 2)
                        }
                        self.failed_test_runs.append({
                            "code": generated_test,
                            "error_message": "Timeout"
                        })
                    else:
                        self.logger.info(f"Test generated failed due to runtime error.")
                        error_message = extract_error_message(stdout, self.language)
                        failure_details = {
                            "status": "FAIL",
                            "reason": "Test failures",
                            "exit_code": exit_code,
                            "stderr": stderr,
                            "stdout": error_message,
                            "test": generated_test,
                            "line_coverage": round(self.current_coverage[0] * 100, 2),
                            "branch_coverage": round(self.current_coverage[1] * 100, 2)
                        }
                        self.failed_test_runs.append(
                            {
                                "code": generated_test,
                                "error_message": error_message
                            }
                        )

                    return failure_details

                # # We were able to run the test suite
                # # So we now check for the coverage increase
                # try:
                #     if self.coverage_type == "jacoco":
                #         new_coverage_processor = JacocoCoverage(
                #             project_dir=self.project_dir,
                #             file_path=self.code_coverage_report_path,
                #             src_file_path=self.source_code_file
                #         )
                #     elif self.coverage_type == "pycov":
                #         new_coverage_processor = PycovCoverage(
                #             file_path=self.code_coverage_report_path,
                #             src_file_path=self.source_code_file
                #         )
                #     else:
                #         raise ValueError(f"Unsupported coverage type: {self.coverage_type}")
                #
                #     _, _, new_line_coverage, new_branch_coverage = (
                #         new_coverage_processor.process_coverage_report(
                #             time_of_test_execution_command=time_of_command
                #         )
                #     )

                # except Exception as e:
                #     self.logger.error(f"Error during coverage verification: {e}")
                #     with open(self.test_code_file, "w") as test_file:
                #         test_file.write(original_content)
                #     failure_details = {
                #         "status": "FAIL",
                #         "reason": f"Error during coverage verification: {e}",
                #         "exit_code": exit_code,
                #         "stderr": stderr,
                #         "stdout": stdout,
                #         "test": generated_test,
                #         "line_coverage": round(self.current_coverage[0] * 100, 2),
                #         "branch_coverage": round(self.current_coverage[1] * 100, 2)
                #     }
                #     self.coverage_invalid_tests.append(
                #         {
                #             "code": generated_test,
                #             "error_message": "Coverage verification failed",
                #         }
                #     )
                #     return failure_details

                # if new_line_coverage <= self.current_coverage[0] and new_branch_coverage <= self.current_coverage[1]:
                #     self.logger.info(
                #         "Generated test passed but it did not increase coverage."
                #     )
                #
                #     pass_details = {
                #         "status": "PASS",
                #         "reason": "Coverage did not increase",
                #         "exit_code": exit_code,
                #         "stderr": stderr,
                #         "stdout": "",
                #         "test": generated_test,
                #         "line_coverage": round(self.current_coverage[0] * 100, 2),
                #         "branch_coverage": round(self.current_coverage[1] * 100, 2)
                #     }
                #     self.coverage_invalid_tests.append(
                #         {
                #             "code": generated_test,
                #             "error_message": "Code coverage did not increase",
                #         }
                #     )
                # else:
                # If the test passes and the coverage increases, we return the test as a successful test
                #self.current_coverage = (new_line_coverage, new_branch_coverage)

                # self.logger.info(
                #     f"Test generated which has passed and coverage increased. "
                #     f"Now current coverages are Line: {round(new_line_coverage * 100, 2)}%, Branch: {round(new_branch_coverage * 100, 2)}%"
                # )
                self.logger.info(f"Generated test has passed: {test_name}")
                pass_details = {
                    "status": "PASS",
                    "reason": "",
                    "exit_code": exit_code,
                    "stderr": stderr,
                    "stdout": "",
                    "test": generated_test,
                    "line_coverage": round(self.current_coverage[0] * 100, 2),
                    "branch_coverage": round(self.current_coverage[1] * 100, 2)
                }

                self.relevant_line_number_to_insert_tests_before = relevant_line_number_to_insert_tests_before
                self.relevant_line_number_to_insert_imports_after = relevant_line_number_to_insert_imports_after
                return pass_details
        except Exception as e:
            self.logger.error(f"Error validating test: {e}")
            with open(self.test_code_file, "w") as test_file:
                test_file.write(original_content)
            return {
                "status": "FAIL",
                "reason": f"Error validating test: {e}",
                "exit_code": None,
                "stderr": str(e),
                "stdout": "",
                "test": generated_test,
                "line_coverage": round(self.current_coverage[0] * 100, 2),
                "branch_coverage": round(self.current_coverage[1] * 100, 2)
            }

    def add_new_test_to_test_file(self, generated_test: dict, original_content):
        processed_test = ""
        test_code = generated_test.get("test_code", "").rstrip()
        additional_imports = (generated_test.get("new_imports_code", "") or "").strip()
        if additional_imports and additional_imports[0] == '"' and additional_imports[-1] == '"':
            additional_imports = additional_imports.strip('"')

        # check if additional_imports only contains '"':
        if additional_imports and additional_imports == '""':
            additional_imports = ""

        relevant_line_number_to_insert_tests_before = self.relevant_line_number_to_insert_tests_before
        relevant_line_number_to_insert_imports_after = self.relevant_line_number_to_insert_imports_after

        needed_indent = self.test_headers_indentation

        # now we will remove the initial indent of test code, and insert the needed indent
        test_code_indented = test_code
        if needed_indent:
            initial_indent = len(test_code) - len(test_code.lstrip())
            delta_indent = int(needed_indent) - initial_indent
            if delta_indent > 0:
                test_code_indented = "\n".join(
                    [delta_indent * " " + line for line in test_code.split("\n")]
                )
        test_code_indented = "\n" + test_code_indented.strip("\n") + "\n"

        if test_code_indented and relevant_line_number_to_insert_tests_before:
            original_content_lines = original_content.split("\n")
            test_code_lines = test_code_indented.split("\n")
            processed_test_lines = (
                    original_content_lines[:relevant_line_number_to_insert_tests_before - 1]
                    + test_code_lines
                    + original_content_lines[relevant_line_number_to_insert_tests_before - 1:]
            )
            relevant_line_number_to_insert_tests_before += len(test_code_lines)

            # additional imports for line 'relevant_line_number_to_insert_imports_after
            processed_test = "\n".join(processed_test_lines)
            if relevant_line_number_to_insert_imports_after and additional_imports and additional_imports not in processed_test:
                additional_imports_lines = additional_imports.split("\n")
                processed_test_lines = (
                        processed_test_lines[:relevant_line_number_to_insert_imports_after]
                        + additional_imports_lines
                        + processed_test_lines[relevant_line_number_to_insert_imports_after:]
                )
                relevant_line_number_to_insert_imports_after += len(additional_imports_lines)
                relevant_line_number_to_insert_tests_before += len(additional_imports_lines)

            processed_test = "\n".join(processed_test_lines)
        return processed_test, relevant_line_number_to_insert_imports_after, relevant_line_number_to_insert_tests_before

    def build_prompt_for_fixing(self) -> dict:
        """
        Returns:
            str: prompt that will be used for fixing the failed test case
        """
        failed_test_runs_value = ""
        # Check for existence of failed tests:
        for failed_test in self.failed_test_runs:
            failed_test_str = failed_test_to_string(failed_test)
            failed_test_runs_value += failed_test_str

        prompt_builder = PromptBuilder(
            project_dir=self.project_dir,
            source_code_file=self.source_code_file,
            test_code_file=self.test_code_file,
            failed_test_runs=failed_test_runs_value,
            language=self.language
        )
        # reset failed tests
        self.failed_test_runs = []
        return prompt_builder.build_prompt_for_fixing()

    def fix_failed_tests(self, f_label, iter_num, max_tokens=4096):
        # Check for existence of failed tests, fix until failed tests are empty or at most 5 iterations
        fix_results_list = []
        iter_count = 0
        token_count = 0
        total_cost = 0
        while self.failed_test_runs and iter_count < iter_num:
            try:
                fixing_prompt = self.build_prompt_for_fixing()
                fixed_tests, tokens, cost = self.generate_test_by_prompt_llm(fixing_prompt, max_tokens)
                iter_count += 1
                token_count += tokens
                total_cost += cost
                for fixed_test in fixed_tests.get("new_tests", []):
                    test_result = self.validate_test(fixed_test)
                    test_result['label'] = f"{f_label}_{iter_count}"
                    fix_results_list.append(test_result)
            except Exception as e:
                self.logger.error(f"Error processing failed test runs: {e}")
        return fix_results_list, token_count, total_cost
