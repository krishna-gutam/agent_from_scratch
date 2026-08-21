import json
import urllib.request
import urllib.error
from dotenv import load_dotenv
import os

# Load environment variables using python-dotenv
load_dotenv()

# List of OpenAI-compatible providers and their model endpoint configurations
PROVIDERS = {
    "OpenAI": {
        "api_key_env": "OPENAI_API_KEY",
        "url": "https://api.openai.com/v1/models",
        "headers_fn": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
    },
    "OpenRouter": {
        "api_key_env": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/api/v1/models",
        "headers_fn": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
    },
    "Groq": {
        "api_key_env": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/models",
        "headers_fn": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    },
    "Google Gemini (OpenAI Compatible)": {
        "api_key_env": "GOOGLE_API_KEY",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "headers_fn": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
    }
}

def fetch_models(provider_name, config):
    api_key = os.getenv(config["api_key_env"])
    if not api_key:
        return None

    headers = config["headers_fn"](api_key)
    req = urllib.request.Request(config["url"], headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            models_list = []
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list):
                    models_list = data["data"]
                elif "models" in data and isinstance(data["models"], list):
                    models_list = data["models"]
            elif isinstance(data, list):
                models_list = data

            clean_models = []
            for m in models_list:
                if isinstance(m, dict):
                    model_id = m.get("id") or m.get("name") or str(m)
                else:
                    model_id = str(m)
                clean_models.append(model_id)
            return clean_models

    except Exception:
        return None

def discover_models():
    all_discovered = {}
    
    for provider_name, config in PROVIDERS.items():
        models = fetch_models(provider_name, config)
        if models is not None:
            all_discovered[provider_name] = models

    output_json = json.dumps(all_discovered, indent=2)
    print(output_json)
    
    with open("discovered_models.json", "w", encoding="utf-8") as f:
        f.write(output_json)


