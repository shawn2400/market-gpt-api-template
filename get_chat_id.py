import requests

# שים כאן את הטוקן של הבוט שלך
TOKEN = '7596535716:AAG2ZU4mPB9n-zYFiE_pls_fBuI8vaayQQY'
url = f'https://api.telegram.org/bot{TOKEN}/getUpdates'

response = requests.get(url)
data = response.json()

print("CHAT_ID שלך הוא:")
print(data['result'][-1]['message']['chat']['id'])
