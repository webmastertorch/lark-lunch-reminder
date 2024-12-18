from flask import Flask, request, jsonify
import requests
import time
import threading
import os

app = Flask(__name__)

# 存储上班打卡信息 { user_id: clock_in_time }
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
    # 如果使用 open_id，请将 receive_id_type 改为 open_id 并确保 user_id 为 open_id
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
    # 测试时将等待时间缩短为10秒，以便快速验证
    time.sleep(10)
    if user_id in clock_ins:
        print(f"User {user_id} still not off-duty, sending reminder...")
        send_message(user_id, "您已经连续工作5小时，请尽快休息并下班打卡（如果需要）。")
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

    # 将同一index的状态变化存储起来，以便分析
    # 预期：每个index应该有两条记录：一条on，一条off
    # 根据最后你描述的逻辑:
    # 最新index的两条记录中:
    #   第一条: on & current_status=Normal
    #   第二条: off & current_status有两种情况:
    #       - current_status='' 表示实际为 "clock in"
    #       - current_status='Normal' 表示实际为 "clock out"
    index_map = {}
    for change in status_changes:
        idx = change.get("index")
        work_type = change.get("work_type")
        current_status = change.get("current_status", "")
        print(f"Found work_type={work_type}, current_status={current_status} for user {user_id} at index={idx}")
        if idx not in index_map:
            index_map[idx] = []
        # 存储 (work_type, current_status)
        index_map[idx].append((work_type, current_status))

    if not index_map:
        print(f"User {user_id} no index data, no action.")
        return jsonify({"code": 0, "msg": "success"})

    max_index = max(index_map.keys())
    records = index_map[max_index]

    # 预期records有两条：(on, Normal) 和 (off, ... )
    # 根据第二条 off 的 current_status 判断是上班还是下班
    if len(records) == 2:
        first = records[0]  # (on, Normal)
        second = records[1] # (off, either '' or 'Normal')
        # 确保第一条是on且Normal
        if first[0] == "on" and first[1] == "Normal":
            # 判断second
            if second[0] == "off":
                if second[1] == "":
                    # 第二条 off 的 current_status = '' 表示实际为 clock in (上班)
                    # 用户此时是上班状态，我们记录并启动计时
                    clock_ins[user_id] = punch_time
                    print(f"User {user_id} is actually clock in at index={max_index}, starting check thread.")
                    t = threading.Thread(target=check_and_notify, args=(user_id, punch_time))
                    t.start()
                elif second[1] == "Normal":
                    # 第二条 off 的 current_status = 'Normal' 表示实际为 clock out (下班)
                    # 用户已下班，如果之前记录有用户则删除
                    if user_id in clock_ins:
                        del clock_ins[user_id]
                        print(f"User {user_id} is actually clock out at index={max_index}, removed from clock_ins.")
                    else:
                        print(f"User {user_id} is actually clock out at index={max_index}, but not in clock_ins.")
                else:
                    # 如果出现其他状态，打印出来以便调试
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
