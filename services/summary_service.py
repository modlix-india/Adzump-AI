import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def merge_summaries(summaries: list[str]) -> str:
    """Merge multiple summaries into one coherent summary using GPT."""
    if not summaries:
        return "No summaries were provided."

    combined_text = "\n".join(summaries)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert summarizer."},
            {
                "role": "user",
                "content": f"Combine the following partial summaries into one detailed and coherent summary. "
                           f"Make it approximately 600–800 words long, in a single continuous paragraph. "
                           f"Ensure clarity, logical flow, and readability.\n\n{combined_text}"
            }
        ],
        max_tokens=1200
    )

    return response.choices[0].message.content.strip()
