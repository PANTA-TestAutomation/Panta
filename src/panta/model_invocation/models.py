class Models:
    MISTRAL_MIXTRAL_8X7B_INSTRUCT_V0_1 = "mistral.mixtral-8x7b-instruct-v0:1"
    META_LLAMA3_70B_INSTRUCT_V1_0 = "meta.llama3-70b-instruct-v1:0"
    GPT_3_5_TURBO_0125 = "gpt-3.5-turbo-0125"
    GPT_4O = "gpt-4o-2024-08-06"
    GPT_4O_MINI = "gpt-4o-mini-2024-07-18"
    META_LLAMA3_1_405b_INSTRUCT_V1_0 = "meta.llama3-1-405b-instruct-v1:0"    
    META_LLAMA3_3_70b_INSTRUCT_V1_0 = "bedrock/us.meta.llama3-3-70b-instruct-v1:0"
    DEEPSEEK_R1 = "deepseek-r1"
    CLAUDE_3_5_HAIKU = "claude-3-5-haiku-20241022"
    MISTRAL_LARGE = "bedrock/mistral.mistral-large-2407-v1:0"
    GEMINI_3_1_FLASH_LITE = "gemini/gemini-3.1-flash-lite-preview"

    # Dictionary to map short names to actual model identifiers
    SHORT_TO_FULL_MODEL_MAP = {
        "gpt-4o": GPT_4O,
        "gpt-4o-mini": GPT_4O_MINI,
        "llama3-1": META_LLAMA3_1_405b_INSTRUCT_V1_0,
        "llama3-3": META_LLAMA3_3_70b_INSTRUCT_V1_0,
        "deepseek-r1": DEEPSEEK_R1,
        "claude3-5": CLAUDE_3_5_HAIKU,
        "mistral-large": MISTRAL_LARGE,
        "gemini-flash-lite": GEMINI_3_1_FLASH_LITE
    }

def validate_and_map_model(model_name: str) -> str:
    """Validate the model name and map to its full identifier."""
    if model_name not in Models.SHORT_TO_FULL_MODEL_MAP:
        raise ValueError(f"Invalid model '{model_name}'. Valid options are: {', '.join(Models.SHORT_TO_FULL_MODEL_MAP.keys())}")
    return Models.SHORT_TO_FULL_MODEL_MAP[model_name]
