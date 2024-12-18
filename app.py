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
    # 如果你的用户ID实际上是 open_id，请将下面的 receive_id_type 改为 open_id 并确保 user_id 是 open_id
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
    # 测试时将5小时缩短为10秒
    time.sleep(10)

    if user_id in clock_ins:
        print(f"User {user_id} still not off-duty, sending reminder...")
        send_message(user_id, "测试提醒：您已经连续工作5小时，请尽快休息并下班打卡（如果需要）。")
        send_message(HR_USER_ID, f"员工 {user_id} 已连续5小时未下班。")
    else:
        print(f"User {user_id} is off-duty now, no reminder needed.")

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

    # 在本次事件中有多个 on/off 变化，我们最终只关心最后的状态
    # 在处理完所有 changes 后再决定是否打卡上班或下班
    final_state = None  # "on"表示最终上班状态，"off"表示最终下班状态
    for change in status_changes:
        work_type = change.get("work_type")
        print(f"Found work_type={work_type} for user {user_id}")
        # 每次读取 work_type 都更新 final_state
        # 最后一次的状态将决定用户最终状态
        if work_type == "on":
            final_state = "on"
        elif work_type == "off":
            final_state = "off"

    # 根据最终状态更新 clock_ins
    if final_state == "on":
        # 用户最终为上班状态，将其记录并启动线程
        clock_ins[user_id] = punch_time
        print(f"User {user_id} final state: ON duty at {punch_time}, starting check thread.")
        t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
        t.start()
    elif final_state == "off":
        # 用户最终为下班状态，从记录中移除（如果存在）
        if user_id in clock_ins:
            del clock_ins[user_id]
            print(f"User {user_id} final state: OFF duty, removed from clock_ins.")
        else:
            print(f"User {user_id} final state: OFF duty but not found in clock_ins, no action needed.")
    else:
        # 如果 final_state 既不是 on 也不是 off，说明没有相关打卡变化
        print(f"User {user_id} no on/off final state detected, no action.")

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
