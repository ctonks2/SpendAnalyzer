"""Simple LLM client wrapper for Mistral (mock or real)"""
import os
import json
import yaml
import requests
from requests.exceptions import RequestException


CONFIG_PATH = os.path.join(os.getcwd(), "configs", "llm.yaml")
DEFAULT_MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/generate"
DEFAULT_MODEL = "mistral-7b-instruct"
DEFAULT_MISTRAL_AGENT_CONV_ENDPOINT = "https://api.mistral.ai/v1/conversations"


class LLMClient:
    def __init__(self):
        # Prefer environment variable, fall back to configs/llm.yaml
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            try:
                if os.path.exists(CONFIG_PATH):
                    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                        cfg = yaml.safe_load(fh) or {}
                        # support either 'mistral_api_key' or generic 'api_key'
                        self.api_key = cfg.get("mistral_api_key") or cfg.get("api_key")
            except Exception:
                self.api_key = None
        self.mock = self.api_key is None
        # set defaults for model/endpoint and agent conversation endpoint
        self.endpoint = DEFAULT_MISTRAL_ENDPOINT
        self.model = DEFAULT_MODEL
        self.agent_conv_endpoint = DEFAULT_MISTRAL_AGENT_CONV_ENDPOINT
        # optional agent id
        self.agent_id = os.getenv("MISTRAL_AGENT_ID")
        # try to load overrides from config
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                    cfg = yaml.safe_load(fh) or {}
                    self.endpoint = cfg.get("mistral_endpoint") or self.endpoint
                    self.model = cfg.get("model") or self.model
                    self.agent_conv_endpoint = cfg.get("mistral_agent_conv_endpoint") or self.agent_conv_endpoint
                    self.agent_id = cfg.get("mistral_agent_id") or self.agent_id
        except Exception:
            pass

    def set_api_key(self, key, persist=False):
        """Set the API key for this client. If persist=True, save to configs/llm.yaml."""
        self.api_key = key
        self.mock = False if key else True
        os.environ["MISTRAL_API_KEY"] = key or ""
        if persist:
            try:
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                # merge with existing config if present
                cfg = {}
                if os.path.exists(CONFIG_PATH):
                    try:
                        with open(CONFIG_PATH, "r", encoding="utf-8") as rfh:
                            cfg = yaml.safe_load(rfh) or {}
                    except Exception:
                        cfg = {}
                cfg["mistral_api_key"] = key
                with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                    yaml.safe_dump(cfg, fh)
            except Exception:
                # Don't crash the app if writing fails; caller can handle messaging
                pass

    def set_agent_id(self, agent_id, persist=False):
        """Set the Mistral agent id and optionally persist to configs/llm.yaml"""
        self.agent_id = agent_id
        if persist:
            try:
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                cfg = {}
                if os.path.exists(CONFIG_PATH):
                    try:
                        with open(CONFIG_PATH, "r", encoding="utf-8") as rfh:
                            cfg = yaml.safe_load(rfh) or {}
                    except Exception:
                        cfg = {}
                cfg["mistral_agent_id"] = agent_id
                with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                    yaml.safe_dump(cfg, fh)
            except Exception:
                pass

    def start_agent_conversation(self, agent_id=None, inputs=None):
        """Start a conversation with a Mistral agent using the (beta) conversations API.

        This posts JSON: {"agent_id": <id>, "inputs": <inputs>} to the configured
        agent conversation endpoint and returns the parsed JSON response or an
        error dict.
        """
        aid = agent_id or self.agent_id
        if not aid:
            return {"error": "no agent_id configured"}
        # Normalize inputs into the expected list-of-messages format
        # Acceptable forms: list of {role,content}, a dict with 'text', or a plain string
        inputs_list = None
        if isinstance(inputs, list):
            inputs_list = inputs
        elif isinstance(inputs, dict):
            if "text" in inputs:
                inputs_list = [{"role": "user", "content": inputs["text"]}]
            elif "role" in inputs and "content" in inputs:
                inputs_list = [inputs]
            else:
                # fallback: stringify dict
                inputs_list = [{"role": "user", "content": json.dumps(inputs)}]
        elif isinstance(inputs, str):
            inputs_list = [{"role": "user", "content": inputs}]
        else:
            inputs_list = [{"role": "user", "content": ""}]

        payload = {"agent_id": aid, "inputs": inputs_list}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(self.agent_conv_endpoint, json=payload, headers=headers, timeout=30)
            # provide helpful error body if status >=400
            if resp.status_code >= 400:
                # try to include JSON detail when available
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text
                return {"error": f"agent request failed: {resp.status_code}", "body": body}
            return resp.json()
        except RequestException as e:
            # include response text if available
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text
                return {"error": f"agent request failed: {e}", "body": body}
            return {"error": f"agent request failed: {e}"}

    def ask(self, prompt, context=None):
        # In mock mode, return a canned response summarizing available context
        if self.mock:
            summary = f"(mock) I received your prompt: '{prompt[:120]}'"
            if context is not None:
                if isinstance(context, list):
                    summary += f" — I see {len(context)} transactions in context."
                else:
                    summary += " — I see context provided."
            summary += "\n(Real Mistral integration is not implemented in this prototype.)"
            return summary
        # Build the full prompt. If a context (list of transactions) is provided,
        # append a short serialized context to the prompt so the model can reason
        # about recent transactions.
        if context is not None:
            if isinstance(context, list):
                # Limit context size to avoid huge payloads
                ctx_snippet = json.dumps(context[:200], default=str)
            else:
                ctx_snippet = json.dumps(context, default=str)
            full_input = f"Context:\n{ctx_snippet}\n\nUser prompt:\n{prompt}"
        else:
            full_input = prompt

        # If an agent id is configured, prefer using the agent conversations API
        if self.agent_id:
            agent_inputs = {"text": full_input}
            agent_res = self.start_agent_conversation(inputs=agent_inputs)
            if isinstance(agent_res, dict) and agent_res.get("error"):
                return f"Agent error: {agent_res.get('error')}"
            # Try to extract text from common fields in agent response
            if isinstance(agent_res, dict):
                # Mistral agent may include 'outputs' or 'results'
                if "outputs" in agent_res and isinstance(agent_res["outputs"], list):
                    out = agent_res["outputs"][0]
                    if isinstance(out, dict):
                        # content may be a list of pieces
                        content = out.get("content") or out.get("text") or out
                        if isinstance(content, list):
                            texts = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
                            if texts:
                                return "\n".join(texts)
                        elif isinstance(content, str):
                            return content
                if "results" in agent_res and isinstance(agent_res["results"], list):
                    first = agent_res["results"][0]
                    contents = first.get("content") or []
                    for c in contents:
                        if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                            return c.get("text") or c.get("output") or ""
                # fallback - return JSON
                try:
                    return json.dumps(agent_res)
                except Exception:
                    return str(agent_res)

        payload = {
            "model": self.model,
            "input": full_input,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
        except RequestException as e:
            return f"LLM API request failed: {e}"

        try:
            data = resp.json()
        except Exception:
            return f"LLM returned non-JSON response: {resp.text[:1000]}"

        # Try to parse known response formats. Mistral's /v1/generate typically
        # returns a 'results' array with content entries containing 'type' and 'text'.
        if isinstance(data, dict):
            # Mistral-style
            if "results" in data and isinstance(data["results"], list) and data["results"]:
                first = data["results"][0]
                contents = first.get("content") or []
                for c in contents:
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        return c.get("text") or c.get("output") or ""
                # fallback: join any text fields
                text_parts = [c.get("text") for c in contents if isinstance(c, dict) and c.get("text")]
                if text_parts:
                    return "\n".join(text_parts)

            # OpenAI-style
            if "choices" in data and isinstance(data["choices"], list) and data["choices"]:
                first = data["choices"][0]
                return first.get("text") or first.get("message", {}).get("content") or str(first)

        # As a last resort, return the full JSON string
        return json.dumps(data)
