import os
import shutil
import time

from .panta_logger import pantaLogger
from .model_invocation.models import validate_and_map_model
from .command_executor import CommandExecutor
from .report_generator import ReportGenerator
from .unit_test_generator import UnitTestGenerator
from .symprompt import SymPrompt
from .templates import TEST_CLASS_JUNIT_3, TEST_CLASS_JUNIT_4, TEST_CLASS_JUNIT_5
from .cfg.src.comex.codeviews.combined_graph.combined_driver import line_number_to_node_id_mapping
from .cfg.src.comex.codeviews.CFG.CFG_driver import CFGDriver
from .utils import read_file
from .utils import get_code_language


def get_class_name(file_path):
    file_name = os.path.basename(file_path)
    class_name = os.path.splitext(file_name)[0]
    return class_name


class Panta:
    def __init__(self, args):
        self.args = args
        self.logger = pantaLogger.initialize_logger(__name__)
        if args.run_symprompt:
            self.report_label = "_".join(['symprompt', args.model])
        else:
            self.report_label = "_".join([args.prompt_type, args.model])
            if not self.args.pick_two_paths:
                self.report_label = "_".join([args.prompt_type, args.model, "one"])

        # Validate and map the model argument before passing it to UnitTestGenerator
        try:
            self.args.model = validate_and_map_model(args.model)
        except ValueError as e:
            self.logger.error(str(e))
            raise
        self.test_dependencies = self.extract_test_dependency()
        self.validate_paths()
        self.duplicate_test_file()

        self.test_gen = UnitTestGenerator(
            project_dir=args.project_directory,
            source_code_file=args.source_code_file,
            test_code_file=args.test_file_output_path,
            code_coverage_report_path=args.code_coverage_report_path,
            test_execution_command=args.test_execution_command,
            test_code_command_dir=args.test_code_command_dir,
            test_dependencies=self.test_dependencies,
            included_files=args.included_files,
            coverage_type=args.coverage_type,
            target_coverage=args.target_coverage,
            prompt_type=args.prompt_type,
            additional_instructions=args.additional_instructions,
            llm_model=args.model)

    def extract_test_dependency(self):
        try:
            stdout, stderr, exit_code, time_of_command, command_duration = CommandExecutor.run_command(
                command=self.args.test_dependency_command, cwd=self.args.test_code_command_dir
            )
            output = ""
            if exit_code == 0:
                output = '\n'.join(
                    line.replace("[INFO]", "").replace(":test", "").strip()
                    for line in stdout.strip().splitlines()
                )
            return output
        except Exception as e:
            self.logger.error(str(e))
            return ""

    def validate_paths(self):
        if not os.path.isfile(self.args.source_code_file):
            raise FileNotFoundError(f"Source file not found at {self.args.source_code_file}")

        test_file_dir = os.path.dirname(self.args.test_code_file)
        test_class_name = get_class_name(self.args.test_code_file)
        # Ensure the directory for the test file exists
        if test_file_dir and not os.path.exists(test_file_dir):
            os.makedirs(test_file_dir, exist_ok=True)

        # Create an empty test file if it does not exist
        if not os.path.isfile(self.args.test_code_file) or os.path.getsize(self.args.test_code_file) == 0:
            self.initial_test_class_skeleton(test_class_name)

    def initial_test_class_skeleton(self, test_class_name):
        """
        In the case, the test class is empty, we create a test class skeleton with basic package, imports and dummy test
        :return:
        """
        language = get_code_language(self.args.source_code_file)
        src_code = read_file(self.args.source_code_file)
        cfg_driver = CFGDriver(language, src_code)
        _, node_id_to_line_numbers_mapping = line_number_to_node_id_mapping(src_code, cfg_driver.CFG_nodes)
        imports_lines = cfg_driver.file_obj["imports"]
        src_code_lines = src_code.split('\n')
        f = open(self.args.test_code_file, 'a')
        if imports_lines:
            last_import_id = imports_lines[-1]["id"]
            last_line_for_imports = node_id_to_line_numbers_mapping[last_import_id][-1]
            f.writelines("\n".join(src_code_lines[:last_line_for_imports]))

        # TODO: get the junit version from dependencies instead of user input
        if self.args.junit_version == 3:
            test_class_template = TEST_CLASS_JUNIT_3.format(test_class_name=test_class_name)
        elif self.args.junit_version == 5:
            test_class_template = TEST_CLASS_JUNIT_5.format(test_class_name=test_class_name)
        else:
            test_class_template = TEST_CLASS_JUNIT_4.format(test_class_name=test_class_name)

        f.writelines(test_class_template)
        f.close()

    def duplicate_test_file(self):
        if self.args.test_file_output_path != "":
            shutil.copy(self.args.test_code_file, self.args.test_file_output_path)
        else:
            self.args.test_file_output_path = self.args.test_code_file

    def run(self):
        iteration_count = 0
        test_results_list = []
        no_coverage_increase = 0

        # self.test_gen.initial_test_suite_analysis()
        self.test_gen.initial_test_suite_analysis_AST()
        try:
            while (
                    self.test_gen.current_coverage[0] < (self.test_gen.target_coverage / 100)
                    and iteration_count < self.args.maximum_iterations
                    and no_coverage_increase < self.args.no_coverage_increase_iterations
            ):
                cur_line_cov = round(self.test_gen.current_coverage[0] * 100, 2)
                cur_branch_cov = round(self.test_gen.current_coverage[1] * 100, 2)
                self.logger.info(f"Current line Coverage: {cur_line_cov}%, branch coverage: {cur_branch_cov}%")
                g_label = f"g_{iteration_count}"
                f_label = f"f_{iteration_count}"

                time_start = time.time()
                if int(cur_line_cov) == 0 and int(cur_branch_cov) == 0:
                    self.logger.info(f"initial tests generation using baseline type of prompt")
                    generated_tests_dict, gen_token_count, gen_cost = self.test_gen.generate_init_tests(g_label, max_tokens=4096)
                else:
                    generated_tests_dict, gen_token_count, gen_cost = self.test_gen.generate_tests(g_label, max_tokens=4096,
                                                                        pick_two_paths=self.args.pick_two_paths)

                for generated_test in (generated_tests_dict.get("new_tests") or []):
                    test_result = self.test_gen.validate_test(generated_test)
                    test_result["label"] = g_label
                    test_results_list.append(test_result)

                # collect code coverage after generation phase
                self.test_gen.run_coverage()
                info_dict_gen = {
                    "status": "INFO",
                    "label": g_label,
                    "reason": time.time() - time_start,
                    "exit_code": gen_cost,
                    "stderr": "",
                    "stdout": "",
                    "test": "",
                    "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
                    "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
                }
                test_results_list.append(info_dict_gen)

                if self.args.enable_fixing:
                    # a separate phase to fix the failed tests in current generation iteration
                    iter_num = self.args.enable_fixing
                    fix_results_list, fix_token_count, fix_cost = self.test_gen.fix_failed_tests(f_label, iter_num, max_tokens=4096)
                    for fix_result in fix_results_list:
                        test_results_list.append(fix_result)

                    # collect coverage after fixing phase
                    self.test_gen.run_coverage()
                    info_dict_fix = {
                        "status": "INFO",
                        "label": f_label,
                        "reason": time.time() - time_start,
                        "exit_code": fix_cost,
                        "stderr": "",
                        "stdout": "",
                        "test": "",
                        "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
                        "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
                    }
                    test_results_list.append(info_dict_fix)
                else:
                    self.logger.info("fixing phase is disabled.")

                if self.test_gen.current_coverage[0] < (self.test_gen.target_coverage / 100):
                    new_line_cov = round(self.test_gen.current_coverage[0] * 100, 2)
                    new_branch_cov = round(self.test_gen.current_coverage[1] * 100, 2)
                    if new_line_cov > cur_line_cov or new_branch_cov > cur_branch_cov:
                        line_cov_increase = new_line_cov - cur_line_cov
                        branch_cov_increase = new_branch_cov - cur_branch_cov
                        self.logger.info(f"Iteration {iteration_count} increased "
                                         f"line coverage {round(line_cov_increase, 2)}%, "
                                         f"branch coverage {round(branch_cov_increase, 2)}%")
                        no_coverage_increase = 0
                    else:
                        self.logger.info(
                            f"Iteration {iteration_count} cannot increase coverage.")
                        no_coverage_increase += 1

                iteration_count += 1
        except Exception as e:
            self.logger.error("iteration stops due to error: ", e)

        if self.test_gen.current_coverage[0] >= (self.test_gen.target_coverage / 100):
            self.logger.info(
                f"Reached above target coverage of {self.test_gen.target_coverage}% "
                f"(Current Coverage: ({round(self.test_gen.current_coverage[0] * 100, 2)}%, "
                f"{round(self.test_gen.current_coverage[1] * 100, 2)}%)) "
                f"in {iteration_count} iterations."
            )
        elif iteration_count == self.args.maximum_iterations:
            failure_message = (f"Reached maximum iteration limit without achieving desired coverage. "
                               f"Current Coverage: ({round(self.test_gen.current_coverage[0] * 100, 2)}%, "
                               f"{round(self.test_gen.current_coverage[1] * 100, 2)}%)")
            self.logger.error(failure_message)
        elif no_coverage_increase == self.args.no_coverage_increase_iterations:
            failure_message = (f"Reached maximum iteration limit without improving coverage. "
                               f"Current Coverage: ({round(self.test_gen.current_coverage[0] * 100, 2)}%, "
                               f"{round(self.test_gen.current_coverage[1] * 100, 2)}%)")
            self.logger.error(failure_message)
        file_name = self.args.source_code_file.split("/")[-1]
        file_name = file_name.split(".")[0]
        name_list = [file_name, self.args.prompt_type, self.args.report_filepath]
        report_file = "_".join(name_list)

        current_dir = os.path.dirname(os.path.abspath(__file__))
        panta_root = os.path.abspath(os.path.join(current_dir, "../../"))
        report_path = os.path.join(panta_root, "result-files", self.report_label) + "/"
        info_dict = {
            "status": "INFO",
            "reason": "",
            "exit_code": 0,
            "stderr": "",
            "stdout": self.test_gen.prompt_builder.path_history,
            "test": "",
            "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
            "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
        }
        test_results_list.append(info_dict)
        if not os.path.exists(report_path):
            os.makedirs(report_path)
        ReportGenerator.generate_report(test_results_list, report_path + report_file)
        self.logger.info("Report generated successfully at: " + report_path)

    def run_symprompt(self):
        test_results_list = []

        self.test_gen.initial_test_suite_analysis_AST()

        symprompt = SymPrompt(project_dir=self.args.project_directory, source_code_file=self.args.source_code_file,
                              llm_model=self.args.model, junit_version=self.args.junit_version)
        cost = symprompt.generate_test()
        generated_tests = symprompt.generated_tests

        for method in generated_tests.keys():
            for index, g_test in enumerate(generated_tests[method]):
                test_result = self.test_gen.validate_test(g_test)
                test_result["label"] = f"{method}_{index}"
                test_results_list.append(test_result)
        self.test_gen.run_coverage()
        info_dict = {
            "status": "INFO",
            "reason": "",
            "exit_code": cost,
            "stderr": "",
            "stdout": "",
            "test": "",
            "line_coverage": round(self.test_gen.current_coverage[0] * 100, 2),
            "branch_coverage": round(self.test_gen.current_coverage[1] * 100, 2)
        }
        test_results_list.append(info_dict)
        file_name = self.args.source_code_file.split("/")[-1]
        file_name = file_name.split(".")[0]
        name_list = [file_name, "symprompt", self.args.report_filepath]
        report_file = "_".join(name_list)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        panta_root = os.path.abspath(os.path.join(current_dir, "../../"))
        report_path = os.path.join(panta_root, "result-files", self.report_label) + "/"
        if not os.path.exists(report_path):
            os.makedirs(report_path)
        ReportGenerator.generate_report(test_results_list, report_path + report_file)
        self.logger.info("Report generated successfully at: " + report_path + report_file)
