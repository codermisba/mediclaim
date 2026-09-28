"""Show the real structured output from the two reliable candidates."""

import base64
import time

from google import genai
from google.genai import types

from services import gemini
from services.sample_data import ensure_sample_documents

client = genai.Client(api_key=gemini.settings.gemini_api_key)
paths = ensure_sample_documents()
card = next(p for n, p in paths.items() if n.endswith(".png"))
card_bytes = base64.b64encode(card.read_bytes()).decode()

SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "member_id": types.Schema(type=types.Type.STRING),
        "provider": types.Schema(type=types.Type.STRING),
    },
    required=["member_id", "provider"],
)

print("reading the generated insurance card image\n")

for name in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]:
    r = client.models.generate_content(
        model=name,
        contents=[
            types.Part.from_text(
                text="Read the membership card image. Return the member id and insurer name."
            ),
            types.Part.from_bytes(data=card_bytes, mime_type="image/png"),
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": SCHEMA,
            "max_output_tokens": 300,
        },
    )
    print(f"{name}:\n  {r.text}\n")
    time.sleep(2)
