from flask import Flask, request, jsonify
import requests
import time
import threading
import os

app = Flask(__name__)

# 用于保存用户的上班打卡记录：{ user_id: clock_in_time }
clock_ins = {}

# 从环境变量中获取 APP_ID 和 APP_SECRET (部署时会用到环境变量)
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
    # 设置token过期时间（约2小时）
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
    # 等待5小时(5*3600秒=18000秒)
    # 测试时可改成10秒: time.sleep(10)
    time.sleep(10)

    # 检查用户是否还未下班打卡
    if user_id in clock_ins:
        # 给用户发送提醒消息
        send_message(user_id, "您已经连续工作5小时，请尽快休息并下班打卡（如果需要）。")

        # 给HR发送提醒，将"HR_USER_ID"替换为实际HR的用户ID
        HR_USER_ID = os.environ.get("HR_USER_ID", "DEFAULT_HR_ID")
        send_message(HR_USER_ID, f"员工 {user_id} 已连续5小时未下班。")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    # 事件订阅验证
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})
    event_type = event.get("type")

    # 用户上班打卡事件
    if event_type == "attendance_punch_in":
        user_id = event["user_id"]
        clock_in_time = event["punch_time"]
        clock_ins[user_id] = clock_in_time

        # 启动一个线程等待5小时后检查
        t = threading.Thread(target=check_and_notify, args=(user_id, clock_in_time))
        t.start()

    # 用户下班打卡事件
    if event_type == "attendance_punch_out":
        user_id = event["user_id"]
        if user_id in clock_ins:
            del clock_ins[user_id]

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    # Railway提供PORT环境变量，我们用它，否则默认为5000端口
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
