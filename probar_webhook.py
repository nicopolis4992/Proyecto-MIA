import httpx

payload = {
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "messages": [
                            {
                                "from": "593999999999",
                                "type": "text",
                                "text": {"body": "Hola, cuanto cuesta el bano para un perro grande?"},
                            }
                        ]
                    }
                }
            ]
        }
    ]
}

response = httpx.post("http://localhost:8000/webhook", json=payload)
print("Status:", response.status_code)