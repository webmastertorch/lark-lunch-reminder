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
TARGET_DEPT_ID = "8egg27ff74c9ec8a"

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
    url = f"https://open.larksuite.com/open-apis/contact/v3/users/{user_id}?user_id_type=user_id"
    headers = {
        "Authorization": f"Bearer {get_bot_access_token()}"
    }
    resp = requests.get(url, headers=headers)
    data = resp.json()
    return data

def check_user_department(user_id):
    user_data = get_user_info(user_id)
    if user_data.get("code") != 0:
        print(f"Failed to get user info for {user_id}, response: {user_data}")
        return False

    user_info = user_data.get("data", {}).get("user", {})
    dept_ids = user_info.get("department_ids", [])
    print(f"User {user_id} departments: {dept_ids}")
    return TARGET_DEPT_ID in dept_ids

def get_user_name(user_id):
    user_data = get_user_info(user_id)
    if user_data.get("code") == 0:
        user_info = user_data.get("data", {}).get("user", {})
        return user_info.get("name", user_id)  # 如果没有name字段，则退化为使用user_id
    else:
        print(f"Failed to get user name for {user_id}, using user_id instead.")
        return user_id

def check_and_notify(user_id, clock_in_time):
    print(f"Check started for {user_id}, time: {clock_in_time}")
    time.sleep(10)  # 测试时短一些，实际应为5*3600秒
    if user_id in clock_ins:
        print(f"User {user_id} still not off-duty, checking department before sending reminder...")
        if check_user_department(user_id):
            print(f"User {user_id} is in target department {TARGET_DEPT_ID}, sending reminder...")
            user_name = get_user_name(user_id)  # 获取用户名
            send_message(user_id, "您已经连续工作5小时，请尽快休息并下班打卡(如果需要)。")
            send_message(HR_USER_ID, f"员工 {user_name} 已连续5小时未下班。")
        else:
            print(f"User {user_id} is not in department {TARGET_DEPT_ID}, no message sent.")
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
