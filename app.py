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
    print("Token response:", data)
    BOT_ACCESS_TOKEN = data.get("tenant_access_token")
    if BOT_ACCESS_TOKEN:
        TOKEN_EXPIRY = current_time + 7000
    else:
        print("Failed to get tenant_access_token. Check APP_ID/APP_SECRET and permissions.")
    return BOT_ACCESS_TOKEN

def send_message(user_id, text):
    # 如有需要，用 open_id 时请改为 receive_id_type=open_id 并确保 user_id 为 open_id
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
    print(f"Sending message to {user_id}: {resp_data}")
    return resp_data

def check_and_notify(user_id, clock_in_time):
    print(f"Check started for {user_id}, time: {clock_in_time}")
    # 测试用：减少等待时间，避免长时间等待
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
    print("Received event:", data)

    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})

    header = data.get("header", {})
    event = data.get("event", {})

    create_time_ms = header.get("create_time", 0)
    punch_time = int(create_time_ms) / 1000.0 if create_time_ms else time.time()

    user_id = event.get("employee_id")
    status_changes = event.get("status_changes", [])

    # 对同一index的变化进行记录，保存按出现顺序的work_type列表
    index_map = {}
    for change in status_changes:
        idx = change.get("index")
        work_type = change.get("work_type")
        print(f"Found work_type={work_type} for user {user_id} at index={idx}")
        if idx not in index_map:
            index_map[idx] = []
        index_map[idx].append(work_type)

    if not index_map:
        print(f"User {user_id} no on/off final state detected, no action.")
        return jsonify({"code": 0, "msg": "success"})

    # 寻找最大index，即最新的打卡记录
    max_index = max(index_map.keys())
    # 查看该index的work_type列表，最后一个出现的work_type才是最终状态
    final_state = index_map[max_index][-1]
    print(f"User {user_id} final latest index={max_index}, final state={final_state}")

    if final_state == "on":
        # 最终状态为on，用户目前在上班，启动计时
        clock_ins[user_id] = punch_time
        print(f"User {user_id} final state: ON duty at {punch_time}, starting check thread.")
        t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
        t.start()
    else:
        # 最终状态为off，用户已下班
        if user_id in clock_ins:
            del clock_ins[user_id]
            print(f"User {user_id} final state: OFF duty, removed from clock_ins.")
        else:
            print(f"User {user_id} final state: OFF duty but not found in clock_ins, no action needed.")

    return jsonify({"code": 0, "msg": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Starting app on port:", port)
    app.run(host="0.0.0.0", port=port)
