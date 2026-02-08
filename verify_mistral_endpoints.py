import json
import requests
from spend_analyzer.llm_client import LLMClient

c = LLMClient()
agent = c.agent_id or "ag_019c3ec3fae177c08ac7900fb8d49969"
inputs = [{"role": "user", "content": "Verification: please reply OK"}]
headers = {"Authorization": f"Bearer {c.api_key}", "Content-Type": "application/json"}

candidates = [
    "https://api.mistral.ai/beta/conversations.start",
    "https://api.mistral.ai/beta/conversations",
    "https://api.mistral.ai/v1/conversations.start",
    "https://api.mistral.ai/v1/conversations",
    f"https://api.mistral.ai/v1/agents/{agent}/converse",
    f"https://api.mistral.ai/v1/agents/{agent}/conversations",
    f"https://api.mistral.ai/agents/{agent}/converse",
]

payloads = [
    {"agent_id": agent, "inputs": inputs},
    {"agent_id": agent, "inputs": inputs},
]

for url in candidates:
    try:
        r = requests.post(url, json={"agent_id": agent, "inputs": inputs}, headers=headers, timeout=15)
        status = r.status_code
        text = r.text
    except Exception as e:
        status = None
        text = str(e)
    print("URL:", url)
    print("Status:", status)
    print("Response:", text[:1000])
    print("---")
