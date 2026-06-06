import requests
import json

url = "https://api.bocha.cn/v1/web-search"

payload = json.dumps({
  "query": "天空为什么是蓝色的？",
  "summary": True,
  "count": 10
})

headers = {
  'Authorization': 'Bearer sk-********',
  'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.json())