import logging
from .panta_logger import pantaLogger
from .config_loader import get_settings
from jinja2 import Environment, StrictUndefined
from .cfg.src.comex.codeviews.combined_graph.combined_driver import CombinedDriver, line_number_to_node_id_mapping
from .cfg.src.comex.tree_parser.parser_driver import pre_process_src_code
from .command_executor import CommandExecutor
from .templates import TEST_CLASS_JUNIT_4_IMPORTS, TEST_CLASS_JUNIT_3_IMPORTS, TEST_CLASS_JUNIT_5_IMPORTS
from .utils import read_file
from .yaml_parser_utils import load_yaml
from .model_invocation.llm_invocation import LLMInvocation
from .utils import get_code_language

MAX_TESTS_PER_RUN = 4


def generate_paths(method):
    paths = method["paths"]
    candidate_paths = []
    for index, path in enumerate(paths):
        path_conditions_str = ""
        path_returns_str = ""
        for node in path["path"]:
            if node['conditional'] is not None:
                path_conditions_str += f"{node['statement']} is {node['conditional']}\n"
            if node['statement'].startswith('return'):
                path_returns_str += f"{node['statement'].replace('return', '').strip()}\n"

        path_str = ""
        if path_conditions_str:
            path_str += "when " + path_conditions_str
        if path_returns_str:
            path_str += "returns: " + path_returns_str
        candidate_paths.append((index, path_str))
    return candidate_paths


class SymPrompt:

    def __init__(self,
                 project_dir: str,
                 source_code_file: str,
                 llm_model: str,
                 junit_version: int):

        self.prompt = {}
        self.project_dir = project_dir
        self.source_code_file = source_code_file
        self.source_file_name = source_code_file.split("/")[-1]
        self.language = get_code_language(source_code_file)
        self.source_file = read_file(source_code_file)
        cfg_driver = CombinedDriver(src_language=self.language, src_code=self.source_file)
        self.cfg_obj = cfg_driver.file_obj
        self.cfg_node_to_line = cfg_driver.node_id_to_line_number
        self.methods_under_test_with_paths = self.extract_paths_for_each_method_under_test()
        self.focal_class_context = self.generate_focal_class_context()
        self.generated_tests = {}
        if junit_version == 3:
            self.test_context = self.extract_test_dependency() + f"\n{TEST_CLASS_JUNIT_3_IMPORTS}"
        elif junit_version == 5:
            self.test_context = self.extract_test_dependency() + f"\n{TEST_CLASS_JUNIT_5_IMPORTS}"
        else:
            self.test_context = self.extract_test_dependency() + f"\n{TEST_CLASS_JUNIT_4_IMPORTS}"

        self.logger = pantaLogger.initialize_logger(__name__)
        self.llm_invoker = LLMInvocation(model=llm_model)

    def extract_test_dependency(self):
        try:
            stdout, stderr, exit_code, time_of_command, command_duration = CommandExecutor.run_command(
                command="mvn dependency:list -DexcludeTransitive=true | grep ':test'", cwd=self.project_dir
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

    def generate_focal_class_context(self):
        src_code_lines = self.source_file.split('\n')
        clz_obj = self.cfg_obj["class_objects"][0]
        first_method = clz_obj['methods_under_test'][0]
        first_method_start_id = first_method['method_declaration']['id']
        first_method_start_line = self.cfg_node_to_line[first_method_start_id][0] - 1
        focal_context_lines = "\n".join(src_code_lines[:first_method_start_line])
        focal_context_lines = pre_process_src_code(self.language, focal_context_lines)
        return focal_context_lines

    def generate_focal_method_context(self, method):
        src_code_lines = self.source_file.split('\n')
        paths = method["paths"]
        method_calls_in_class = set()
        for index, path in enumerate(paths):
            for m in path['method_calls_within_class']:
                method_calls_in_class.add(m)

        methods_in_class = ""
        for method_call in method_calls_in_class:
            values = method_call.rsplit(',', 2)
            start_id = values[1].strip()
            end_id = values[2].strip()
            start_line = self.cfg_node_to_line[int(start_id)][0] - 1

            if end_id == "None":
                method_lines = "\n".join(src_code_lines[start_line:])
            else:
                end_line = self.cfg_node_to_line[int(end_id)][-1] - 1
                method_lines = "\n".join(src_code_lines[start_line:end_line])
            method_lines = pre_process_src_code(self.language, method_lines)

            methods_in_class += method_lines

        focal_method_nodes = method['method_declaration']['nodes']

        focal_start_line = self.cfg_node_to_line[focal_method_nodes[0]][0] - 1
        focal_end_line = self.cfg_node_to_line[focal_method_nodes[-1]][-1] - 1

        focal_method_lines = "\n".join(src_code_lines[focal_start_line:focal_end_line + 1])
        focal_method_lines = pre_process_src_code(self.language, focal_method_lines)
        return methods_in_class, focal_method_lines

    def extract_paths_for_each_method_under_test(self):
        # there may be multiple classes defined in the file, we focus on the outer class for now
        clz_obj = self.cfg_obj["class_objects"][0]
        methods_under_test = clz_obj["methods_under_test"]
        methods_with_paths = []
        for method in methods_under_test:
            name = method["method_declaration"]["name"]
            complexity = method["method_declaration"]["complexity"]
            method_label = f"{method['method_declaration']['name']}_{method['method_declaration']['id']}"
            method_value = method['method_declaration']['value']
            candidate_paths = generate_paths(method)
            method_calls, focal_method = self.generate_focal_method_context(method)
            methods_with_paths.append((name, complexity, method_label, method_value, candidate_paths,
                                       method_calls, focal_method))

        return methods_with_paths

    def generate_test(self, max_tokens=4096):
        cost_total = 0
        for method in self.methods_under_test_with_paths:
            # method is (name, complexity, method_label, method_value, candidate_paths, method_calls, focal_method)
            method_name = method[0]
            complexity = method[1]
            method_label = method[2]
            method_signiture = method[3]
            candidate_paths = method[4]
            method_calls_in_class = method[5]
            focal_method_lines = method[6]
            print(method_label)
            self.generated_tests[method_label] = []
            for path in candidate_paths:
                self.prompt = self.build_prompt_for_each_path(method_name, method_signiture, method_label,
                                                              method_calls_in_class, focal_method_lines, path)

                generated_test, cost = self.generate_test_by_prompt_llm(self.prompt, max_tokens)
                cost_total += cost
                if 'single_test' in generated_test and generated_test['single_test']:
                    self.generated_tests[method_label].extend(generated_test['single_test'])
        return cost_total

    def generate_test_by_prompt_llm(self, prompt: dict, max_tokens=4096):
        response, prompt_token_count, response_token_count, cost = (
            self.llm_invoker.call_model(prompt=prompt,
                                        max_tokens=max_tokens))
        self.logger.info(f"Total token count for LLM {self.llm_invoker.model}: "
                         f"{prompt_token_count + response_token_count}")
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
            tests_dict = {}

        return tests_dict, cost

    def build_prompt_for_each_path(self, method_name, method_signiture, method_label,
                                   method_calls_in_class, focal_method_lines, path) -> dict:
        variables = {
            "source_file_name": self.source_file_name,
            "source_file": self.source_file
        }
        environment = Environment(undefined=StrictUndefined)
        try:
            system_prompt = environment.from_string(
                get_settings().test_generation_symprompt.system
            ).render(variables)

            path_str = path[1]
            method_str = f"\n=========\nPlease generate test case for method {method_name}, \n{method_signiture}\n"
            test_generation_prompt = method_str + path_str

            focal_context = self.focal_class_context + "\n" + method_calls_in_class + "\n# focal method\n" \
                            + focal_method_lines

            user_prompt = environment.from_string(
                get_settings().test_generation_symprompt.user
            ).render(variables, focal_class_context=focal_context,
                     test_context=self.test_context,
                     test_generation_prompt=test_generation_prompt,
                     generated_tests=self.generated_tests[method_label])

            self.logger.debug(f"system_prompt: {system_prompt}")
            self.logger.debug(f"user_prompt: {user_prompt}")
        except Exception as e:
            logging.error(f"Error rendering prompt: {e}")
            return {"system": "", "user": ""}

        # print(f"#### user_prompt:\n\n{user_prompt}")
        return {"system": system_prompt, "user": user_prompt}