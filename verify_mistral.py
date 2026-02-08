from spend_analyzer.llm_client import LLMClient
import json

c = LLMClient()
inputs = [{"role": "user", "content": "Verification: please reply OK"}]
res = c.start_agent_conversation(inputs=inputs)
print(json.dumps(res, indent=2))
