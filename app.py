from flask import Flask, request, jsonify
import requests
import time
import threading
import os

app = Flask(__name__)

clock_ins = {}

APP_ID = os.environ.get("APP_ID", "YOUR_APP_ID")
APP_SECRET = os.environ.get("APP_SECRET", "YOUR_APP_SECRET")

BOT_ACCESS_TOKEN = None
TOKEN_EXPIRY = 0

def get_bot_access_token():
    global BOT_ACCESS_TOKEN, TOKEN_EXPIRY
    current_time = int(time.time())
    if BOT_ACCESS_TOKEN is not None and current_time < TOKEN_EXPIRY:
        return BOT_ACCESS_TOKEN

    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    data = resp.json()
    BOT_ACCESS_TOKEN = data["tenant_access_token"]
    TOKEN_EXPIRY = current_time + 7000
    return BOT_ACCESS_TOKEN

def send_message(user_id, text):
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=user_id"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": user_id,
        "msg_type": "text",
        "content": {
            "text": text
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

def check_and_notify(user_id, clock_in_time):
    # 等待5小时
    # 测试时可改短：time.sleep(10)
    time.sleep(10)

    if user_id in clock_ins:
        send_message(user_id, "您已经连续工作5小时，请尽快休息并下班打卡（如果需要）。")
        HR_USER_ID = os.environ.get("gc5gb18e", "gc5gb18e")  # 替换为实际的 HR 用户ID
        send_message(HR_USER_ID, f"员工 {user_id} 已连续5小时未下班。")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    header = data.get("header", {})
    event = data.get("event", {})

    # 从header中获取事件发生的时间戳(毫秒)
    create_time_ms = header.get("create_time")
    if create_time_ms:
        # 转换为秒，更易读，也可不转换直接使用毫秒
        punch_time = int(create_time_ms) / 1000.0
    else:
        # 如果没有时间戳信息，就使用当前时间
        punch_time = time.time()

    user_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    # 遍历所有状态变化，如果其中有work_type为on或off，就当作上/下班打卡处理
    for change in status_changes:
        work_type = change.get("work_type")
        if work_type == "on":
            # 上班打卡逻辑
            clock_ins[user_id] = punch_time
            t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
            t.start()
        elif work_type == "off":
            # 下班打卡逻辑
            if user_id in clock_ins:
                del clock_ins[user_id]

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
