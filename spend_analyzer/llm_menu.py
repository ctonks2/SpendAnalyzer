import os
import json
from datetime import datetime
import textwrap

class LLMMenu:
    def __init__(self, llm_client, dm):
        self.llm = llm_client
        self.dm = dm

    def ask_llm(self, user_id):
        print("Entering LLM chat. Type 'exit' or 'back' to return to the menu.")
        messages = []
        context = self.dm.get_transactions_by_user(user_id)
        context_included = False
        while True:
            try:
                q = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            if q.lower() in ("exit", "back", "quit"):
                break
            if not context_included and getattr(self.llm, "agent_id", None) and context:
                ctx_snippet = json.dumps(context[:200], default=str)
                full_content = f"Context (my transactions):\n{ctx_snippet}\n\nMy question:\n{q}"
                context_included = True
            else:
                full_content = q
            messages.append({"role": "user", "content": full_content})
            if getattr(self.llm, "agent_id", None):
                res = self.llm.start_agent_conversation(inputs=messages)
                if isinstance(res, dict) and res.get("error"):
                    body = res.get("body")
                    print("Agent error:", res.get("error"), "", body if body else "")
                    continue
                assistant_text = None
                if isinstance(res, dict):
                    if "outputs" in res and isinstance(res["outputs"], list) and res["outputs"]:
                        out = res["outputs"][0]
                        content = out.get("content") if isinstance(out, dict) else None
                        if isinstance(content, list):
                            texts = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
                            assistant_text = "\n".join(t for t in texts if t)
                        elif isinstance(content, str):
                            assistant_text = content
                    elif "results" in res and isinstance(res["results"], list) and res["results"]:
                        first = res["results"][0]
                        contents = first.get("content") or []
                        if isinstance(contents, list):
                            texts = [c.get("text") for c in contents if isinstance(c, dict) and c.get("text")]
                            assistant_text = "\n".join(t for t in texts if t)
                        elif isinstance(contents, str):
                            assistant_text = contents
                if assistant_text is None:
                    try:
                        assistant_text = json.dumps(res)
                    except Exception:
                        assistant_text = str(res)
                print("Assistant:", assistant_text)
                messages.append({"role": "assistant", "content": assistant_text})
                save_choice = input("\nSave this recommendation? (y/N): ").strip().lower()
                if save_choice == "y":
                    self.save_recommendation(q, assistant_text, user_id)
            else:
                context = self.dm.get_transactions_by_user(user_id)
                resp = self.llm.ask(q, context=context)
                print("Assistant:\n", resp)
                save_choice = input("\nSave this recommendation? (y/N): ").strip().lower()
                if save_choice == "y":
                    self.save_recommendation(q, resp, user_id)
        return None

    def save_recommendation(self, question, response, user_id):
        categories = [
            "Budget Tips",
            "Food & Groceries",
            "Shopping Advice",
            "Entertainment",
            "Utilities",
            "Travel",
            "Health",
            "Other"
        ]
        print("\nChoose category for this recommendation:")
        for i, cat in enumerate(categories, 1):
            print(f"{i}) {cat}")
        try:
            cat_choice = input("Category number (default: 8): ").strip() or "8"
            cat_idx = int(cat_choice) - 1
            if 0 <= cat_idx < len(categories):
                category = categories[cat_idx]
            else:
                category = "Other"
        except (ValueError, IndexError):
            category = "Other"
        date_str = input("Date for this recommendation (YYYY-MM-DD, default: today): ").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        rec_dir = os.path.join(os.getcwd(), "reports")
        os.makedirs(rec_dir, exist_ok=True)
        rec_file = os.path.join(rec_dir, "recommendations.json")
        recommendation = {
            "user_id": user_id,
            "date": date_str,
            "category": category,
            "question": question,
            "response": response,
            "saved_at": datetime.now().isoformat()
        }
        try:
            recs = []
            if os.path.exists(rec_file):
                try:
                    with open(rec_file, "r", encoding="utf-8") as f:
                        recs = json.load(f)
                except Exception:
                    recs = []
            recs.append(recommendation)
            with open(rec_file, "w", encoding="utf-8") as f:
                json.dump(recs, f, indent=2, default=str)
            print(f"✓ Recommendation saved to {rec_file}")
        except Exception as e:
            print(f"Error saving recommendation: {e}")
