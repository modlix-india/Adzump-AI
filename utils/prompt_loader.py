import os

def load_prompt(prompt_name: str) -> str:
    # Get the root directory (Adzump-AI) regardless of where this file is
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(root_dir, 'prompts', prompt_name)
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()
