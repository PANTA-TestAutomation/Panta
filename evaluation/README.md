## Defects4J subjects evaluation

The following script analyzes each project to provide src-test pairs, testable methods, cyclomatic complexity and coverage information.
Results for each subject are in `{subject_name}-codefiles.json`, `subject_statistics.csv` contains overall statistics.

```console
python3 compute_statistics.py java
```

`class_list.csv` contains the classes that have high complexity larger than 10.

To generate tests for the classes in `class_list.csv` by Panta
```console
python3 execute_classes_with_high_complexity.py control llama3-3      # results are under `../../result-files/control_llama3-3`
```

To generate tests for other customized class list, e.g. `high_complexity_classes.csv` by Panta
```console
python3 execute_classes_with_high_complexity.py control llama3-3 --class-list high_complexity_classes.csv   # results are under `../../result-files/control_llama3-3`
```

To generate tests for the classes in `class_list.csv` by SymPrompt
```console
python3 execute_symprompt.py symprompt llama3-3            # results are under `../../result-files/symprompt_llama3-3`
```

Parse result files to extract results under `../../result-files`
```console
python3 result-html-parse.py                   # coverage for Panta ablation study and SymPrompt
python3 result-parser-different-models.py      # coverage for different models
python3 extract_pass_rate.py                   # pass rate comparison 
```
Files that contains the statistics of the results are `coverage_statistics.csv`, `coverage_statistics_models.csv`, `pass_rate_statistics.csv`

`coverage_statistics.xlsx` contains the tables to analyze the results. 


