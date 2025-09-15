from openai import OpenAI
from dotenv import load_dotenv
import os 

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def get_client():
    """Create a new OpenAI client per request (safe for multiprocessing)."""
    return OpenAI(api_key=OPENAI_API_KEY)

async def chat_completion(messages: list, model: str = "gpt-4.1"):
    client = get_client()  
    response = client.chat.completions.create(
        model=model,
        messages=messages
    )
    return response.choices[0].message.content.strip()
 