import os
import time
import json
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

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
    print("Token response:", data)
    BOT_ACCESS_TOKEN = data.get("tenant_access_token")
    if BOT_ACCESS_TOKEN:
        TOKEN_EXPIRY = current_time + 7000
    else:
        print("Failed to get tenant_access_token. Check APP_ID/APP_SECRET and permissions.")
    return BOT_ACCESS_TOKEN

def send_message(user_id, text):
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=user_id"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}",
        "Content-Type": "application/json"
    }
    safe_text = text.replace("（", "(").replace("）", ")")
    content_str = json.dumps({"text": safe_text})
    payload = {
        "receive_id": user_id,
        "msg_type": "text",
        "content": content_str
    }
    response = requests.post(url, headers=headers, json=payload)
    resp_data = response.json()
    print(f"Sending message to {user_id}: {resp_data}")
    return resp_data

def get_user_info(user_id):
    """根据 user_id 获取用户信息，返回用户数据字典"""
    url = f"https://open.larksuite.com/open-apis/contact/v3/users/{user_id}?user_id_type=user_id"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}"
    }
    resp = requests.get(url, headers=headers)
    return resp.json()

def check_and_notify(user_id, clock_in_time):
    print(f"Check started for {user_id}, time: {clock_in_time}")
    # 等待5小时（测试时可用10秒验证，正式使用应为5*3600）
    time.sleep(10)
    if user_id in clock_ins:
        print(f"User {user_id} still not off-duty, getting user name and sending reminder...")
        # 获取用户姓名
        user_data = get_user_info(user_id)
        if user_data.get("code") == 0:
            user_name = user_data["data"]["user"].get("name", user_id)  # 如果没有name，用user_id代替
        else:
            user_name = user_id

        # 发送提醒给用户
        send_message(user_id, "您已经连续工作5小时，请尽快休息并下班打卡(如果需要)。")

        # 发送提醒给HR，使用用户姓名
        send_message(HR_USER_ID, f"员工 {user_name} 已连续5小时未下班。")
    else:
        print(f"User {user_id} is off-duty now, no reminder needed.")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Received event:", data)

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    header = data.get("header", {})
    event = data.get("event", {})

    create_time_ms = header.get("create_time", 0)
    punch_time = int(create_time_ms) / 1000.0 if create_time_ms else time.time()

    user_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    index_map = {}
    for change in status_changes:
        idx = change.get("index")
        work_type = change.get("work_type")
        current_status = change.get("current_status", "")
        print(f"Found work_type={work_type}, current_status={current_status} for user {user_id} at index={idx}")
        if idx not in index_map:
            index_map[idx] = []
        index_map[idx].append((work_type, current_status))

    if not index_map:
        print(f"User {user_id} no index data, no action.")
        return jsonify({"code": 0, "msg": "success"})

    max_index = max(index_map.keys())
    records = index_map[max_index]

    # 按照之前逻辑判断clock in和clock out
    if len(records) == 2:
        first = records[0]  # (on, Normal)
        second = records[1] # (off, '' or Normal)
        if first[0] == "on" and first[1] == "Normal":
            if second[0] == "off":
                if second[1] == "":
                    # 实为clock in
                    clock_ins[user_id] = punch_time
                    print(f"User {user_id} is actually clock in at index={max_index}, starting check thread.")
                    t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
                    t.start()
                elif second[1] == "Normal":
                    # 实为clock out
                    if user_id in clock_ins:
                        del clock_ins[user_id]
                        print(f"User {user_id} is actually clock out at index={max_index}, removed from clock_ins.")
                    else:
                        print(f"User {user_id} is actually clock out at index={max_index}, but not in clock_ins.")
                else:
                    print(f"User {user_id} at index={max_index}, off status unexpected: {second[1]}")
            else:
                print(f"User {user_id} at index={max_index}, second record not off: {second}")
        else:
            print(f"User {user_id} at index={max_index}, first record not (on, Normal): {first}")
    else:
        print(f"User {user_id} at index={max_index} has unexpected record count: {len(records)}")

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
