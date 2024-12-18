from flask import Flask, request, jsonify
import requests
import time
import threading
import os

app = Flask(__name__)

# 用于存储上班打卡信息 { user_id: clock_in_time }
clock_ins = {}

APP_ID = os.environ.get("APP_ID", "YOUR_APP_ID")
APP_SECRET = os.environ.get("APP_SECRET", "YOUR_APP_SECRET")
HR_USER_ID = os.environ.get("HR_USER_ID", "HR_USER_ID")

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
    print("Token response:", data)  # 调试打印token获取结果
    BOT_ACCESS_TOKEN = data.get("tenant_access_token")
    if BOT_ACCESS_TOKEN:
        TOKEN_EXPIRY = current_time + 7000
    else:
        print("Failed to get tenant_access_token. Check APP_ID/APP_SECRET and permissions.")
    return BOT_ACCESS_TOKEN

def send_message(user_id, text):
    # 如需使用open_id，请将receive_id_type改为open_id，并确保user_id变量为open_id
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
    resp_data = response.json()
    print(f"Sending message to {user_id}: {resp_data}")  # 调试打印消息发送结果
    return resp_data

def check_and_notify(user_id, clock_in_time):
    print(f"Check started for {user_id}, time: {clock_in_time}")  # 调试打印线程开始执行
    # 测试时将5小时改为10秒，加快验证
    time.sleep(10)

    if user_id in clock_ins:
        print(f"User {user_id} still not off-duty, sending reminder...")  # 调试打印用户仍未下班
        send_message(user_id, "测试提醒：您已经连续工作5小时，请尽快休息并下班打卡（如果需要）。")
        send_message(HR_USER_ID, f"员工 {user_id} 已连续5小时未下班。")
    else:
        print(f"User {user_id} is off-duty now, no reminder needed.")  # 调试打印用户已下班

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Received event:", data)  # 调试打印接收到的原始事件数据

    # 事件订阅验证
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    header = data.get("header", {})
    event = data.get("event", {})

    # 获取事件发生时间（毫秒）
    create_time_ms = header.get("create_time", 0)
    punch_time = int(create_time_ms) / 1000.0 if create_time_ms else time.time()

    user_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    # 遍历状态变化，查找上班或下班打卡
    for change in status_changes:
        work_type = change.get("work_type")
        print(f"Found work_type={work_type} for user {user_id}")  # 调试打印识别到的work_type
        if work_type == "on":
            # 上班打卡逻辑
            clock_ins[user_id] = punch_time
            print(f"User {user_id} clocked in at {punch_time}, starting check thread.")  # 调试打印上班打卡记录
            t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
            t.start()
        elif work_type == "off":
            # 下班打卡逻辑
            if user_id in clock_ins:
                del clock_ins[user_id]
                print(f"User {user_id} clocked out, removed from clock_ins.")  # 调试打印下班打卡记录

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
