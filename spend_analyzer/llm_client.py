"""Simple LLM client wrapper for Mistral (mock or real)"""
import os
import json


class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        self.mock = self.api_key is None

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

        # Real API call would be implemented here. Placeholder:
        return "(Mistral) API client not implemented in the prototype."
